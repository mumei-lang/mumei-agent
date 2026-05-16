"""Coverage for latent debug and dense property feature flags."""
from __future__ import annotations

from unittest.mock import Mock

import numpy as np

from agent.config import AgentConfig
from agent.latent_decoder import LatentDecoder
from agent.latent_encoder import LatentEncoder
from agent.metrics import Metrics
from agent.strategies.dense_property_generator import DensePropertyGenerator
from agent.strategies.generate_strategy import generate_code
from agent.strategies.latent_debug_strategy import LatentDebugStrategy


SOURCE_CODE = (
    "atom bounded_add(a: i64, b: i64) -> i64\n"
    "    requires: a >= 0;\n"
    "    ensures: result >= a;\n"
    "    body: { a + b }\n"
)


class RaisingEncoder:
    """Encoder double that forces latent debug fallback."""

    def encode_to_latent(
        self,
        source_code: str,
        verification_report: dict[str, object],
    ) -> np.ndarray:
        raise RuntimeError("encoder unavailable")


def _mock_response(content: str) -> Mock:
    response = Mock()
    response.choices = [Mock()]
    response.choices[0].message.content = content
    return response


def test_default_nlae_flags_disable_debug_and_enable_dense_only(monkeypatch) -> None:
    """Latent debug is opt-in while dense properties stay enabled by default."""
    monkeypatch.delenv("ENABLE_LATENT_DEBUG", raising=False)
    monkeypatch.delenv("ENABLE_DENSE_PROPERTIES", raising=False)
    monkeypatch.delenv("ENABLE_LATENT_PROTOCOL", raising=False)

    config = AgentConfig()

    assert config.enable_latent_debug is False
    assert config.enable_dense_properties is True
    assert config.enable_latent_protocol is False


def test_latent_encoder_decoder_basic_functionality() -> None:
    """Latent vectors are populated and decoder applies conservative edits."""
    encoder = LatentEncoder()
    decoder = LatentDecoder()
    report = {
        "failure_type": "effect_mismatch",
        "counterexample": {"a": 1},
        "structured_unsat_core": ["requires"],
    }

    latent_vector = encoder.encode_to_latent(SOURCE_CODE, report)
    edit_vector = np.zeros_like(latent_vector)
    edit_vector[10] = 1.0
    decoded = decoder.decode_to_source(edit_vector, SOURCE_CODE)

    assert latent_vector.dtype == np.float32
    assert latent_vector.size > 0
    assert float(latent_vector.sum()) > 0.0
    assert "effects: [Write]" in decoded


def test_latent_debug_strategy_falls_back_on_encoder_error() -> None:
    """Latent debug returns None when encoding fails."""
    result = LatentDebugStrategy().get_fix_with_latent_debug(
        SOURCE_CODE,
        {"failure_type": "precondition_violated"},
        RaisingEncoder(),
        LatentDecoder(),
    )

    assert result is None


def test_dense_property_generator_validates_output_shape() -> None:
    """Dense property generation returns decoded requires, ensures, and raw text."""
    client = Mock()
    client.chat.completions.create.return_value = _mock_response(
        "requires: a >= 0 && b >= 0;\nensures: result == a + b;"
    )

    dense_props = DensePropertyGenerator().generate_dense_properties(
        {"name": "bounded_add", "params": []},
        SOURCE_CODE,
        client,
        "test-model",
    )

    assert dense_props["requires"] == ["a >= 0 && b >= 0"]
    assert dense_props["ensures"] == ["result == a + b"]
    assert "requires:" in dense_props["raw"]


def test_generate_code_uses_default_dense_properties_and_records_metrics(monkeypatch) -> None:
    """Default generation applies dense properties and records at least 50% usage."""
    monkeypatch.delenv("ENABLE_DENSE_PROPERTIES", raising=False)
    monkeypatch.setenv("ENABLE_GENERATION_HEALTH_CHECK", "false")
    client = Mock()
    client.chat.completions.create.side_effect = [
        _mock_response(
            "```mumei\n"
            "atom bounded_add(a: i64, b: i64) -> i64\n"
            "    requires: true;\n"
            "    ensures: true;\n"
            "    body: { a + b }\n"
            "```"
        ),
        _mock_response("requires: a >= 0 && b >= 0;\nensures: result == a + b;"),
    ]
    metrics = Metrics()

    code, verified = generate_code(
        client,
        "test-model",
        {"name": "bounded_add", "params": [], "return_type": "i64"},
        mumei_client=None,
        metrics=metrics,
    )

    assert verified is True
    assert "requires: a >= 0 && b >= 0;" in code
    assert "ensures: result == a + b;" in code
    assert metrics.dense_property_attempts == 1
    assert metrics.dense_property_successes == 1
    assert metrics.dense_property_usage_rate >= 0.5
    assert metrics.to_dict()["dense_property_usage_rate"] >= 0.5
