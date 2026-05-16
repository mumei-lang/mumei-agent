"""Tests for latent-space debugging components."""
from __future__ import annotations

from agent.latent_decoder import LatentDecoder
from agent.latent_encoder import LatentEncoder
from agent.latent_debug_strategy import LatentDebugStrategy as PublicLatentDebugStrategy
from agent.strategies.latent_debug_strategy import LatentDebugStrategy


def test_latent_debug_strategy_initialization() -> None:
    """LatentDebugStrategy initializes."""
    assert LatentDebugStrategy() is not None
    assert PublicLatentDebugStrategy is LatentDebugStrategy


def test_latent_encoder_initialization() -> None:
    """LatentEncoder initializes."""
    assert LatentEncoder() is not None


def test_latent_decoder_initialization() -> None:
    """LatentDecoder initializes."""
    assert LatentDecoder() is not None


def test_latent_encode_decode_roundtrip() -> None:
    """Encode/decode returns a usable vector and source string."""
    encoder = LatentEncoder()
    decoder = LatentDecoder()
    source_code = (
        "atom test(a: i64) -> i64\n"
        "    requires: a > 0;\n"
        "    ensures: true;\n"
        "    body: { a }\n"
    )
    report = {
        "violation_type": "precondition_violated",
        "counterexample": {"a": 0},
    }

    latent_vector = encoder.encode_to_latent(source_code, report)
    decoded_code = decoder.decode_to_source(latent_vector, source_code)

    assert latent_vector is not None
    assert len(latent_vector) > 0
    assert decoded_code


def test_latent_debug_fix_with_mock_report() -> None:
    """Latent debug returns either a candidate fix or fallback None."""
    strategy = LatentDebugStrategy()
    encoder = LatentEncoder()
    decoder = LatentDecoder()
    source_code = "atom safe_div(a: i64, b: i64) -> i64\n    body: { a / b }\n"
    report = {
        "violation_type": "division_by_zero",
        "atom": "safe_div",
        "counterexample": {"b": 0},
    }

    fixed_code = strategy.get_fix_with_latent_debug(
        source_code,
        report,
        encoder,
        decoder,
    )

    assert fixed_code is not None
    assert "requires: b != 0;" in fixed_code
