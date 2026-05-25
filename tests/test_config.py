"""AgentConfig tests for experimental NLA options."""
from __future__ import annotations

from agent.config import AgentConfig


def test_nla_options_default_values(monkeypatch) -> None:
    """NLA defaults keep latent debug and dense properties opt-in."""
    monkeypatch.delenv("ENABLE_LATENT_DEBUG", raising=False)
    monkeypatch.delenv("ENABLE_DENSE_PROPERTIES", raising=False)
    monkeypatch.delenv("ENABLE_LATENT_PROTOCOL", raising=False)
    monkeypatch.delenv("ENABLE_CODE_TO_SPEC", raising=False)
    monkeypatch.delenv("ENABLE_GENERATION_HEALTH_CHECK", raising=False)
    monkeypatch.delenv("ENABLE_SPEC_CODE_MAPPING", raising=False)
    monkeypatch.delenv("ENABLE_AMBIGUITY_DETECTION", raising=False)
    monkeypatch.delenv("ENABLE_INTENT_TRACKING", raising=False)
    monkeypatch.delenv("ENABLE_CONTRACT_ISOLATION", raising=False)
    monkeypatch.delenv("CONTRACT_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("INTENT_DRIFT_THRESHOLD", raising=False)

    config = AgentConfig()

    assert config.enable_latent_debug is False
    assert config.enable_dense_properties is False
    assert config.enable_latent_protocol is False
    assert config.enable_code_to_spec is True
    assert config.enable_generation_health_check is True
    assert config.enable_spec_code_mapping is True
    assert config.enable_ambiguity_detection is True
    assert config.enable_intent_tracking is True
    assert config.enable_contract_isolation is True
    assert config.contract_manifest_path is None
    assert config.intent_drift_threshold == 0.7


def test_nla_options_from_env(monkeypatch) -> None:
    """NLA options can be enabled by environment variables."""
    monkeypatch.setenv("ENABLE_LATENT_DEBUG", "true")
    monkeypatch.setenv("ENABLE_DENSE_PROPERTIES", "true")
    monkeypatch.setenv("ENABLE_LATENT_PROTOCOL", "true")
    monkeypatch.setenv("ENABLE_CODE_TO_SPEC", "false")
    monkeypatch.setenv("ENABLE_GENERATION_HEALTH_CHECK", "false")
    monkeypatch.setenv("ENABLE_SPEC_CODE_MAPPING", "false")
    monkeypatch.setenv("ENABLE_AMBIGUITY_DETECTION", "false")
    monkeypatch.setenv("ENABLE_INTENT_TRACKING", "false")
    monkeypatch.setenv("ENABLE_CONTRACT_ISOLATION", "false")
    monkeypatch.setenv("CONTRACT_MANIFEST_PATH", "contract-manifest.json")
    monkeypatch.setenv("INTENT_DRIFT_THRESHOLD", "0.9")

    config = AgentConfig()

    assert config.enable_latent_debug is True
    assert config.enable_dense_properties is True
    assert config.enable_latent_protocol is True
    assert config.enable_code_to_spec is False
    assert config.enable_generation_health_check is False
    assert config.enable_spec_code_mapping is False
    assert config.enable_ambiguity_detection is False
    assert config.enable_intent_tracking is False
    assert config.enable_contract_isolation is False
    assert config.contract_manifest_path == "contract-manifest.json"
    assert config.intent_drift_threshold == 0.9


def test_nla_options_case_insensitive(monkeypatch) -> None:
    """Boolean parsing accepts common truthy values."""
    monkeypatch.setenv("ENABLE_LATENT_DEBUG", "True")
    monkeypatch.setenv("ENABLE_DENSE_PROPERTIES", "TRUE")
    monkeypatch.setenv("ENABLE_LATENT_PROTOCOL", "1")

    config = AgentConfig()

    assert config.enable_latent_debug is True
    assert config.enable_dense_properties is True
    assert config.enable_latent_protocol is True


def test_nla_options_false_values(monkeypatch) -> None:
    """Non-truthy values override boolean NLA options."""
    for value in ["false", "False", "FALSE", "0", "no", "No", "NO", "off", "OFF"]:
        monkeypatch.setenv("ENABLE_LATENT_DEBUG", value)
        monkeypatch.setenv("ENABLE_DENSE_PROPERTIES", value)
        config = AgentConfig()
        assert config.enable_latent_debug is False
        assert config.enable_dense_properties is False
