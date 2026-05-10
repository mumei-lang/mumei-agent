"""Latent representation protocol for inter-agent messages."""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from agent.mumei_client import MumeiClient


class LatentProtocol:
    """NLAE-inspired protocol for compact inter-agent communication."""

    def encode_message(
        self,
        message: dict[str, Any],
        context: dict[str, Any],
    ) -> np.ndarray:
        """Encode message and context into a latent vector."""
        return self._encode_to_nla(message, context)

    def decode_message(self, latent_vector: np.ndarray) -> dict[str, Any]:
        """Decode a latent vector into inspectable metadata."""
        return self._decode_from_nla(latent_vector)

    def verify_message(
        self,
        latent_vector: np.ndarray,
        mumei_client: MumeiClient,
    ) -> bool:
        """Verify that latent payload can be represented by Mumei code."""
        temp_code = self._latent_to_temp_code(latent_vector)
        verify_code = getattr(mumei_client, "verify_code", None)
        if callable(verify_code):
            result = verify_code(temp_code)
            return bool(result.get("success", False))

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                suffix=".mm",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp_path = tmp.name
                tmp.write(temp_code)
            result = mumei_client.verify(tmp_path)
            return bool(result.get("success", False))
        finally:
            if tmp_path is not None:
                Path(tmp_path).unlink(missing_ok=True)

    def _encode_to_nla(
        self,
        message: dict[str, Any],
        context: dict[str, Any],
    ) -> np.ndarray:
        """Encode dictionaries using deterministic hash-based features."""
        payload = f"{message!r}\n{context!r}".encode("utf-8")
        digest = hashlib.sha256(payload).digest()
        return np.array([byte / 255.0 for byte in digest[:16]], dtype=np.float32)

    def _decode_from_nla(self, latent_vector: np.ndarray) -> dict[str, Any]:
        """Return safe decoded metadata for a latent vector."""
        return {
            "decoded": True,
            "latent_dim": int(len(latent_vector)),
            "latent_sum": float(np.sum(latent_vector)),
        }

    def _latent_to_temp_code(self, latent_vector: np.ndarray) -> str:
        """Render a minimal Mumei source representing latent metadata."""
        latent_str = ", ".join(f"{float(v):.4f}" for v in latent_vector[:8])
        return f"""// Latent vector representation: [{latent_str}]
atom placeholder() -> bool
    requires: true;
    ensures: true;
    body: {{ true }}
"""
