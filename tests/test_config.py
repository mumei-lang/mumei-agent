"""AgentConfig tests for experimental NLA options."""
from __future__ import annotations

from agent.config import AgentConfig


def test_nla_options_default_false(monkeypatch) -> None:
    """NLA options default to false."""
    monkeypatch.delenv("ENABLE_LATENT_DEBUG", raising=False)
    monkeypatch.delenv("ENABLE_DENSE_PROPERTIES", raising=False)
    monkeypatch.delenv("ENABLE_LATENT_PROTOCOL", raising=False)
    monkeypatch.delenv("ENABLE_TRANSPILER", raising=False)
    monkeypatch.delenv("TRANSPILER_LLM_INFERENCE", raising=False)

    config = AgentConfig()

    assert config.enable_latent_debug is False
    assert config.enable_dense_properties is False
    assert config.enable_latent_protocol is False
    assert config.enable_transpiler is False
    assert config.transpiler_llm_inference is False


def test_nla_options_from_env(monkeypatch) -> None:
    """NLA options can be enabled by environment variables."""
    monkeypatch.setenv("ENABLE_LATENT_DEBUG", "true")
    monkeypatch.setenv("ENABLE_DENSE_PROPERTIES", "true")
    monkeypatch.setenv("ENABLE_LATENT_PROTOCOL", "true")
    monkeypatch.setenv("ENABLE_TRANSPILER", "true")
    monkeypatch.setenv("TRANSPILER_LLM_INFERENCE", "true")

    config = AgentConfig()

    assert config.enable_latent_debug is True
    assert config.enable_dense_properties is True
    assert config.enable_latent_protocol is True
    assert config.enable_transpiler is True
    assert config.transpiler_llm_inference is True


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
    """Non-truthy values leave NLA options disabled."""
    for value in ["false", "False", "FALSE", "0", "no", "No", "NO", "off", "OFF"]:
        monkeypatch.setenv("ENABLE_LATENT_DEBUG", value)
        assert AgentConfig().enable_latent_debug is False
