"""Latent representation protocol for inter-agent messages."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agent.mumei_client import MumeiClient


JSONDict = dict[str, object]


@dataclass(frozen=True)
class CompressionResult:
    """Compact payload selected for latent transfer."""

    mode: str
    raw_bytes: int
    compressed_bytes: int
    transfer_bytes: int
    body: bytes


class LatentProtocol:
    """NLAE-inspired protocol for compact inter-agent communication."""

    CURRENT_VERSION = "lp-v2"
    SUPPORTED_VERSIONS = {"lp-v1", "lp-v2"}
    VECTOR_DIM = 16
    AEAD_NONCE_BYTES = 12
    VOLATILE_SEMANTIC_KEYS = {
        "id",
        "request_id",
        "trace_id",
        "timestamp",
        "created_at",
        "updated_at",
        "nonce",
    }

    def __init__(
        self,
        *,
        version: str = CURRENT_VERSION,
        encryption_key: str | bytes | None = None,
        audit_log_path: str | Path | None = None,
    ) -> None:
        if version not in self.SUPPORTED_VERSIONS:
            raise ValueError(f"unsupported latent protocol version: {version}")
        self.version = version
        self.encryption_key = self._coerce_key(encryption_key)
        self.audit_log_path = Path(audit_log_path) if audit_log_path else None
        self.audit_log: list[JSONDict] = []
        self._metadata_by_vector: dict[str, JSONDict] = {}

    def encode_message(
        self,
        message: JSONDict,
        context: JSONDict,
        *,
        previous_message: JSONDict | None = None,
        previous_context: JSONDict | None = None,
        version: str | None = None,
    ) -> np.ndarray:
        """Encode message and context into a latent vector."""
        return self._version_aware_encode(
            message,
            context,
            previous_message=previous_message,
            previous_context=previous_context,
            version=version or self.version,
        )

    def decode_message(self, latent_vector: np.ndarray) -> JSONDict:
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

    def verify_authentication_tag(self, latent_vector: np.ndarray) -> bool:
        """Check the HMAC tag for a vector encoded by this protocol instance."""
        metadata = self._metadata_by_vector.get(self._vector_key(latent_vector))
        if metadata is None:
            return False
        expected = str(metadata["authentication_tag"])
        encoded_frame = str(metadata["encoded_frame"])
        actual = hmac.new(
            self._auth_key(),
            encoded_frame.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, actual)

    def _version_aware_encode(
        self,
        message: JSONDict,
        context: JSONDict,
        *,
        previous_message: JSONDict | None = None,
        previous_context: JSONDict | None = None,
        version: str,
    ) -> np.ndarray:
        """Encode with versioned metadata, compression, and privacy controls."""
        if version not in self.SUPPORTED_VERSIONS:
            raise ValueError(f"unsupported latent protocol version: {version}")

        payload = self._canonical_bytes({"context": context, "message": message})
        previous_payload = None
        if previous_message is not None or previous_context is not None:
            previous_payload = self._canonical_bytes(
                {
                    "context": previous_context or {},
                    "message": previous_message or {},
                }
            )

        compression = self._encode_with_compression(
            payload,
            previous_payload=previous_payload,
        )
        protected_body = self._encrypt(compression.body)
        semantic_hash = self._semantic_hash(message, context)
        payload_hash = hashlib.sha256(payload).hexdigest()
        body_hash = hashlib.sha256(protected_body).hexdigest()
        frame = {
            "body_hash": body_hash,
            "compression_mode": compression.mode,
            "encrypted": self.encryption_key is not None,
            "encryption": "aes-256-gcm" if self.encryption_key is not None else "none",
            "payload_hash": payload_hash,
            "protocol_version": version,
            "semantic_hash": semantic_hash,
        }
        if version == "lp-v1":
            frame["legacy_payload_hash"] = hashlib.sha1(payload).hexdigest()
        encoded_frame = self._canonical_json(frame)
        authentication_tag = hmac.new(
            self._auth_key(),
            encoded_frame.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        digest = hashlib.sha256(
            f"{encoded_frame}:{authentication_tag}".encode("utf-8"),
        ).digest()
        latent_vector = np.array(
            [byte / 255.0 for byte in digest[: self.VECTOR_DIM]],
            dtype=np.float32,
        )

        raw_bytes = compression.raw_bytes
        transfer_bytes = min(compression.transfer_bytes, latent_vector.nbytes)
        reduction_ratio = 0.0
        if raw_bytes:
            reduction_ratio = max(0.0, 1.0 - (transfer_bytes / raw_bytes))
        metadata: JSONDict = {
            "authentication": "hmac-sha256",
            "authentication_tag": authentication_tag,
            "compressed_bytes": compression.compressed_bytes,
            "compression_mode": compression.mode,
            "decoded": True,
            "encoded_frame": encoded_frame,
            "encrypted": self.encryption_key is not None,
            "encryption": "aes-256-gcm" if self.encryption_key is not None else "none",
            "latent_dim": self.VECTOR_DIM,
            "payload_hash": payload_hash,
            "protocol_version": version,
            "raw_bytes": raw_bytes,
            "semantic_hash": semantic_hash,
            "transfer_bytes": transfer_bytes,
            "transfer_reduction_ratio": reduction_ratio,
        }
        self._metadata_by_vector[self._vector_key(latent_vector)] = metadata
        self._audit("encode", metadata)
        return latent_vector

    def _encode_to_nla(
        self,
        message: JSONDict,
        context: JSONDict,
    ) -> np.ndarray:
        """Encode dictionaries using deterministic hash-based features."""
        return self.encode_message(message, context, version="lp-v1")

    def _decode_from_nla(self, latent_vector: np.ndarray) -> JSONDict:
        """Return safe decoded metadata for a latent vector."""
        metadata = self._metadata_by_vector.get(self._vector_key(latent_vector))
        if metadata is not None:
            decoded = dict(metadata)
            decoded.pop("encoded_frame", None)
            decoded["latent_sum"] = float(np.sum(latent_vector))
            self._audit("decode", decoded)
            return decoded
        return {
            "decoded": True,
            "latent_dim": int(len(latent_vector)),
            "latent_sum": float(np.sum(latent_vector)),
            "protocol_version": "unknown",
        }

    def _encode_with_compression(
        self,
        payload: bytes,
        *,
        previous_payload: bytes | None = None,
    ) -> CompressionResult:
        """Compress a payload, preferring a delta body when it is smaller."""
        full = zlib.compress(payload, level=9)
        selected_mode = "zlib"
        selected_body = full

        if previous_payload:
            prefix_len = self._common_prefix_len(payload, previous_payload)
            suffix_len = self._common_suffix_len(
                payload[prefix_len:],
                previous_payload[prefix_len:],
            )
            suffix_start = len(payload) - suffix_len if suffix_len else len(payload)
            delta = self._canonical_bytes(
                {
                    "insert": payload[prefix_len:suffix_start].decode(
                        "utf-8",
                        errors="replace",
                    ),
                    "prefix": prefix_len,
                    "suffix": suffix_len,
                }
            )
            compressed_delta = zlib.compress(delta, level=9)
            if len(compressed_delta) < len(full):
                selected_mode = "zlib-delta"
                selected_body = compressed_delta

        return CompressionResult(
            mode=selected_mode,
            raw_bytes=len(payload),
            compressed_bytes=len(selected_body),
            transfer_bytes=len(selected_body),
            body=selected_body,
        )

    def _semantic_hash(self, message: JSONDict, context: JSONDict) -> str:
        """Hash stable semantic content while ignoring transport volatility."""
        semantic_payload = {
            "context": self._strip_volatile(context),
            "message": self._strip_volatile(message),
        }
        return hashlib.blake2b(
            self._canonical_bytes(semantic_payload),
            digest_size=16,
        ).hexdigest()

    def _latent_to_temp_code(self, latent_vector: np.ndarray) -> str:
        """Render a minimal Mumei source representing latent metadata."""
        latent_str = ", ".join(f"{float(v):.4f}" for v in latent_vector[:8])
        return f"""// Latent vector representation: [{latent_str}]
atom placeholder() -> bool
    requires: true;
    ensures: true;
    body: {{ true }}
"""

    def _audit(self, event: str, metadata: JSONDict) -> None:
        audit_entry: JSONDict = {
            "authentication": metadata.get("authentication", ""),
            "encrypted": bool(metadata.get("encrypted", False)),
            "event": event,
            "payload_hash": metadata.get("payload_hash", ""),
            "protocol_version": metadata.get("protocol_version", ""),
            "semantic_hash": metadata.get("semantic_hash", ""),
            "transfer_bytes": metadata.get("transfer_bytes", 0),
        }
        self.audit_log.append(audit_entry)
        if self.audit_log_path is not None:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_log_path.open("a", encoding="utf-8") as audit_file:
                audit_file.write(json.dumps(audit_entry, sort_keys=True) + "\n")

    def _encrypt(self, body: bytes) -> bytes:
        if self.encryption_key is None:
            return body
        aesgcm = AESGCM(hashlib.sha256(self.encryption_key).digest())
        nonce = os.urandom(self.AEAD_NONCE_BYTES)
        associated_data = f"mumei-agent:{self.version}".encode("utf-8")
        return nonce + aesgcm.encrypt(nonce, body, associated_data)

    def _auth_key(self) -> bytes:
        if self.encryption_key is not None:
            return self.encryption_key
        return b"mumei-agent-latent-protocol"

    def _coerce_key(self, key: str | bytes | None) -> bytes | None:
        if key is None:
            return None
        if isinstance(key, bytes):
            return key
        return key.encode("utf-8")

    def _canonical_bytes(self, payload: object) -> bytes:
        return self._canonical_json(payload).encode("utf-8")

    def _canonical_json(self, payload: object) -> str:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )

    def _strip_volatile(self, value: object) -> object:
        if isinstance(value, dict):
            return {
                str(key): self._strip_volatile(nested_value)
                for key, nested_value in sorted(value.items())
                if str(key).lower() not in self.VOLATILE_SEMANTIC_KEYS
            }
        if isinstance(value, list):
            return [self._strip_volatile(item) for item in value]
        return value

    def _vector_key(self, latent_vector: np.ndarray) -> str:
        return hashlib.sha256(
            np.asarray(latent_vector, dtype=np.float32).tobytes(),
        ).hexdigest()

    def _common_prefix_len(self, left: bytes, right: bytes) -> int:
        limit = min(len(left), len(right))
        for index in range(limit):
            if left[index] != right[index]:
                return index
        return limit

    def _common_suffix_len(self, left: bytes, right: bytes) -> int:
        limit = min(len(left), len(right))
        for index in range(1, limit + 1):
            if left[-index] != right[-index]:
                return index - 1
        return limit
