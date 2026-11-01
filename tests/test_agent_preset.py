from __future__ import annotations

from dataclasses import fields

import pytest

from agent.cli_reference import render_env_reference
from agent.config import AgentConfig, _AGENT_PRESETS
from agent.env_reference import ENV_VARS


PRESET_FIELDS = {
    "CONTROLS_GATE": "controls_gate",
    "ENABLE_CHARTER_GUARD": "enable_charter_guard",
    "ENABLE_EROSION_GUARD": "enable_erosion_guard",
    "ENABLE_LEAN_AI_PROOF": "enable_lean_ai_proof",
    "ENABLE_SELF_CORRECTION": "enable_self_correction",
    "ENABLE_NLAE_MULTI_AGENT": "enable_nlae_multi_agent",
    "ENABLE_LATENT_DEBUG": "enable_latent_debug",
    "ENABLE_DENSE_PROPERTIES": "enable_dense_properties",
    "ENABLE_LATENT_PROTOCOL": "enable_latent_protocol",
}

PRESET_CASES = [
    (preset, name, value)
    for preset, values in _AGENT_PRESETS.items()
    for name, value in values.items()
]


def _scrub_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for entry in ENV_VARS:
        monkeypatch.delenv(entry.name, raising=False)


def test_field_map_covers_every_preset_key() -> None:
    preset_keys = {name for values in _AGENT_PRESETS.values() for name in values}
    assert set(PRESET_FIELDS) == preset_keys


@pytest.mark.parametrize(("preset", "name", "value"), PRESET_CASES)
def test_each_unset_preset_key_sets_its_config_field(
    monkeypatch: pytest.MonkeyPatch,
    preset: str,
    name: str,
    value: str,
) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", preset)

    config = AgentConfig()
    expected = value if name == "CONTROLS_GATE" else value == "true"

    assert getattr(config, PRESET_FIELDS[name]) == expected


@pytest.mark.parametrize(
    ("preset", "name", "explicit_value", "expected"),
    [
        ("experimental", "ENABLE_LATENT_DEBUG", "false", False),
        ("ci-strict", "ENABLE_SELF_CORRECTION", "1", True),
    ],
)
def test_explicit_boolean_environment_value_overrides_preset(
    monkeypatch: pytest.MonkeyPatch,
    preset: str,
    name: str,
    explicit_value: str,
    expected: bool,
) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", preset)
    monkeypatch.setenv(name, explicit_value)

    config = AgentConfig()

    assert getattr(config, PRESET_FIELDS[name]) is expected


def test_explicit_controls_gate_off_overrides_ci_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", "ci-strict")
    monkeypatch.setenv("CONTROLS_GATE", "off")

    assert AgentConfig().controls_gate == "off"


def test_missing_and_empty_preset_match_scrubbed_defaults_field_by_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scrub_environment(monkeypatch)
    baseline = AgentConfig()
    baseline_fields = {entry.name: getattr(baseline, entry.name) for entry in fields(baseline)}

    monkeypatch.setenv("MUMEI_AGENT_PRESET", "")
    empty_preset = AgentConfig()

    assert {
        entry.name: getattr(empty_preset, entry.name) for entry in fields(empty_preset)
    } == baseline_fields
    assert empty_preset.agent_preset is None


def test_unknown_preset_lists_sorted_choices_before_controls_gate_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", "unknown")
    monkeypatch.setenv("CONTROLS_GATE", "invalid")

    with pytest.raises(ValueError) as error:
        AgentConfig()

    message = str(error.value)
    assert "unknown MUMEI_AGENT_PRESET 'unknown'" in message
    assert str(sorted(_AGENT_PRESETS)) in message
    assert "CONTROLS_GATE" not in message


def test_non_preset_environment_keys_keep_their_own_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("ENABLE_INTENT_TRACKING", "false")
    without_preset = AgentConfig()

    monkeypatch.setenv("MUMEI_AGENT_PRESET", "ci-strict")
    with_preset = AgentConfig()

    assert with_preset.enable_intent_tracking is without_preset.enable_intent_tracking is False
    assert with_preset.enable_code_to_spec is without_preset.enable_code_to_spec is True


def test_experimental_lean_proof_still_requires_key_and_non_fixture_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", "experimental")
    assert AgentConfig().lean_ai_proof_active() is False

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("CI_FIXTURE_MODE", "1")
    assert AgentConfig().lean_ai_proof_active() is False

    monkeypatch.setenv("CI_FIXTURE_MODE", "false")
    assert AgentConfig().lean_ai_proof_active() is True


def test_agent_preset_coexists_with_llm_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", "experimental")
    monkeypatch.setenv("MUMEI_LLM_PROFILE", "local-small")

    config = AgentConfig()

    assert config.agent_preset == "experimental"
    assert config.enable_latent_debug is True
    assert config.model == "qwen2.5-coder:1.5b-2k"
    assert config.llm_max_tokens == 2048


def test_agent_preset_is_environment_derived_and_not_a_constructor_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scrub_environment(monkeypatch)
    monkeypatch.setenv("MUMEI_AGENT_PRESET", "experimental")

    assert AgentConfig().agent_preset == "experimental"
    with pytest.raises(TypeError):
        AgentConfig(agent_preset="experimental")


def test_generated_environment_reference_matches_preset_maps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scrub_environment(monkeypatch)
    reference = render_env_reference()

    preset_entry = next(entry for entry in ENV_VARS if entry.name == "MUMEI_AGENT_PRESET")
    assert preset_entry.kind == "value"
    assert preset_entry.default == ""
    assert preset_entry.config_field == "agent_preset"
    assert "explicit environment variable > preset > built-in default" in reference

    for preset, values in _AGENT_PRESETS.items():
        section = reference.split(f"### `{preset}`\n", 1)[1].split("\n### ", 1)[0]
        rendered_values = {
            row.split("|")[1].strip().strip("`"): row.split("|")[2].strip().strip("`")
            for row in section.splitlines()
            if row.startswith("| `")
        }
        assert rendered_values == values
