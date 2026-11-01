"""Report effective agent configuration and its source."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

from agent.config import AgentConfig, _preset_value
from agent.env_reference import ENV_VARS, EnvVar


@dataclass(frozen=True)
class _Entry:
    variable: EnvVar
    raw: str | None
    source: str
    preset: str | None
    effective: Any
    note: str | None = None


def build_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(
            prog="python -m agent config",
            description="Show effective settings and where each value comes from",
        )
    parser.add_argument("--json", action="store_true", help="Output JSON.")
    parser.add_argument("--all", action="store_true", help="Include default values.")
    return parser


def _sanitize_url_value(value: Any) -> Any:
    if not isinstance(value, str) or "://" not in value:
        return value
    scheme, remainder = value.split("://", 1)
    authority_end = min(
        (index for delimiter in ("/", "?", "#") if (index := remainder.find(delimiter)) >= 0),
        default=len(remainder),
    )
    authority = remainder[:authority_end]
    host = authority.rsplit("@", 1)[-1]
    suffix = remainder[authority_end:]
    suffix_end = min(
        (index for delimiter in ("?", "#") if (index := suffix.find(delimiter)) >= 0),
        default=len(suffix),
    )
    return f"{scheme}://{host}{suffix[:suffix_end]}"


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None or value == "":
        return "-"
    return str(value)


def _entries(config: AgentConfig) -> list[_Entry]:
    entries: list[_Entry] = []
    llm_profile_values = AgentConfig._LLM_PROFILES.get(config.llm_profile or "", {})
    for variable in ENV_VARS:
        raw = os.environ.get(variable.name)
        preset = _preset_value(variable.name)
        source = (
            "env"
            if raw is not None
            else "preset"
            if preset is not None
            else "llm-profile"
            if variable.config_field in llm_profile_values
            else "default"
        )
        if not variable.config_field:
            effective = None
        elif hasattr(config, variable.config_field):
            effective = getattr(config, variable.config_field)
        elif raw is not None:
            effective = raw
        elif preset is not None:
            effective = preset
        else:
            effective = variable.default
        note = None
        if (
            variable.name == "ENABLE_LEAN_AI_PROOF"
            and config.enable_lean_ai_proof
            and not config.lean_ai_proof_active()
        ):
            if not config.api_key:
                note = "inactive: no API key"
            elif config.ci_fixture_mode:
                note = "inactive: CI_FIXTURE_MODE"
        entries.append(_Entry(variable, raw, source, preset, effective, note))
    return entries


def _entry_json(entry: _Entry) -> dict[str, Any]:
    variable = entry.variable
    result = {
        "name": variable.name,
        "category": variable.category,
        "source": entry.source,
        "set": entry.raw is not None,
        "default": variable.default,
        "config_field": variable.config_field,
        "description": variable.description,
        "sensitive": variable.sensitive,
    }
    if not variable.sensitive:
        result["value"] = _sanitize_url_value(entry.raw)
        result["effective"] = _sanitize_url_value(entry.effective)
    if entry.note is not None:
        result["note"] = entry.note
    return result


def main(args: argparse.Namespace) -> int:
    try:
        config = AgentConfig()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    entries = _entries(config)
    visible = [entry for entry in entries if args.all or entry.source != "default"]
    if args.json:
        print(
            json.dumps(
                {
                    "agent_preset": config.agent_preset,
                    "llm_profile": config.llm_profile,
                    "env": [_entry_json(entry) for entry in visible],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    print(f"preset: {config.agent_preset or 'none'}")
    print(f"llm profile: {config.llm_profile or 'none'}")
    env_count = sum(entry.source == "env" for entry in entries)
    preset_count = sum(entry.source == "preset" for entry in entries)
    print(
        f"environment ({env_count} from env, {preset_count} from preset, "
        f"of {len(ENV_VARS)} known; values loaded from .env count as env):"
    )
    for entry in visible:
        if entry.variable.sensitive:
            if entry.raw is not None:
                print(f"  {entry.variable.name}: set  [env]")
            elif entry.source == "preset":
                print(
                    f"  {entry.variable.name}: set  "
                    f"[preset {config.agent_preset}]"
                )
            else:
                print(
                    f"  {entry.variable.name} = "
                    f"{_display(entry.variable.default)}  [default]"
                )
            continue
        if entry.raw is not None and not entry.variable.config_field:
            value = _display(_sanitize_url_value(entry.raw))
            print(f"  {entry.variable.name} = {value}  [env, raw]")
            continue
        value = _display(_sanitize_url_value(entry.effective))
        if entry.source == "preset":
            source = f"[preset {config.agent_preset}]"
        elif entry.source == "llm-profile":
            source = f"[llm-profile {config.llm_profile}]"
        else:
            source = f"[{entry.source}]"
        print(f"  {entry.variable.name} = {value}  {source}")
        if entry.note is not None:
            print(f"  ({entry.note})")
    return 0
