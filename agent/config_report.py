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


def _is_sensitive(name: str) -> bool:
    upper_name = name.upper()
    return any(term in upper_name for term in ("TOKEN", "KEY", "SECRET", "PASSWORD"))


def _redact(name: str, value: Any) -> Any:
    return "***" if _is_sensitive(name) and value is not None else value


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None or value == "":
        return "-"
    return str(value)


def _entries(config: AgentConfig) -> list[_Entry]:
    entries: list[_Entry] = []
    for variable in ENV_VARS:
        raw = os.environ.get(variable.name)
        preset = _preset_value(variable.name)
        source = "env" if raw is not None else "preset" if preset is not None else "default"
        if variable.config_field and hasattr(config, variable.config_field):
            effective = getattr(config, variable.config_field)
        elif raw is not None:
            effective = raw
        elif preset is not None:
            effective = preset
        else:
            effective = variable.default
        entries.append(_Entry(variable, raw, source, preset, effective))
    return entries


def _entry_json(entry: _Entry) -> dict[str, Any]:
    variable = entry.variable
    return {
        "name": variable.name,
        "category": variable.category,
        "source": entry.source,
        "set": entry.raw is not None,
        "value": _redact(variable.name, entry.raw),
        "effective": _redact(variable.name, entry.effective),
        "default": variable.default,
        "config_field": variable.config_field,
        "description": variable.description,
    }


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
        value = _display(_redact(entry.variable.name, entry.effective))
        if entry.source == "preset":
            source = f"[preset {config.agent_preset}]"
        else:
            source = f"[{entry.source}]"
        print(f"  {entry.variable.name} = {value}  {source}")
    return 0
