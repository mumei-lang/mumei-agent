"""Tests for latent inter-agent protocol."""
from __future__ import annotations

from unittest.mock import Mock

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
