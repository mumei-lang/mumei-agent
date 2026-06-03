"""Tests for latent inter-agent protocol."""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from agent.latent_protocol import LatentProtocol


def test_latent_protocol_initialization() -> None:
    """LatentProtocol initializes."""
    assert LatentProtocol() is not None


def test_encode_decode_message() -> None:
    """Messages can be encoded and decoded into metadata."""
    protocol = LatentProtocol()
    message = {"action": "generate", "target": "safe_add"}
    context = {"domain": "arithmetic"}

    latent_vector = protocol.encode_message(message, context)
    decoded = protocol.decode_message(latent_vector)

    assert latent_vector is not None
    assert len(latent_vector) == 16
    assert decoded["decoded"] is True
    assert decoded["latent_dim"] == 16


def test_verify_message_with_mock_client_verify_code() -> None:
    """verify_code clients are supported."""
    protocol = LatentProtocol()
    latent_vector = protocol.encode_message({"action": "generate"}, {})

    mock_client = Mock()
    mock_client.verify_code = Mock(return_value={"success": True})

    assert protocol.verify_message(latent_vector, mock_client) is True


def test_semantic_hash_ignores_transport_volatility() -> None:
    """Semantic hashes stay stable across request-local fields."""
    protocol = LatentProtocol()
    message = {"action": "generate", "target": "safe_add", "timestamp": "1"}
    context = {"domain": "arithmetic", "trace_id": "abc"}

    first_hash = protocol._semantic_hash(message, context)
    second_hash = protocol._semantic_hash(
        {**message, "timestamp": "2"},
        {**context, "trace_id": "def"},
    )
    changed_hash = protocol._semantic_hash({**message, "target": "safe_sub"}, context)

    assert first_hash == second_hash
    assert first_hash != changed_hash


def test_version_aware_encode_reports_compression_and_security_metadata() -> None:
    """Encoded metadata includes protocol version, compression, auth, and privacy."""
    protocol = LatentProtocol(encryption_key="latent-secret")
    message = {
        "action": "generate",
        "target": "safe_add",
        "requirements": [
            f"preserve bounded arithmetic invariant {index}" for index in range(60)
        ],
    }

    latent_vector = protocol.encode_message(message, {"domain": "arithmetic"})
    decoded = protocol.decode_message(latent_vector)

    assert decoded["protocol_version"] == "lp-v2"
    assert decoded["encrypted"] is True
    assert decoded["encryption"] == "aes-256-gcm"
    assert decoded["authentication"] == "hmac-sha256"
    assert protocol.verify_authentication_tag(latent_vector) is True
    assert decoded["transfer_reduction_ratio"] >= 0.5
    assert json.dumps(protocol.audit_log)
    assert "bounded arithmetic invariant" not in json.dumps(protocol.audit_log)


def test_diff_compression_is_selected_for_similar_payloads() -> None:
    """Delta compression wins when consecutive payloads differ slightly."""
    protocol = LatentProtocol()
    body = "\n".join(
        f"atom_{index}: requires x >= {index}; ensures result >= {index};"
        for index in range(120)
    )
    previous = {"action": "generate", "target": "proof_block", "body": body}
    current = {
        "action": "generate",
        "target": "proof_block",
        "body": body.replace("ensures result >= 119", "ensures result >= 120"),
    }

    latent_vector = protocol.encode_message(
        current,
        {"domain": "stdlib"},
        previous_message=previous,
        previous_context={"domain": "stdlib"},
    )
    decoded = protocol.decode_message(latent_vector)

    assert decoded["compression_mode"] == "zlib-delta"
    assert decoded["transfer_reduction_ratio"] >= 0.5


def test_unsupported_protocol_version_fails_fast() -> None:
    """Unknown protocol versions are rejected before transfer."""
    protocol = LatentProtocol()

    with pytest.raises(ValueError, match="unsupported latent protocol version"):
        protocol.encode_message({"action": "generate"}, {}, version="lp-v99")
