"""Remove secret values from text before it reaches an LLM prompt or a report.

Two sources are covered: the values of environment variables that
``agent.env_reference`` classifies as sensitive, and credential-shaped
literals in source code (provider token formats, private-key blocks and
string literals assigned to a credential-like name). A redacted value is
replaced with ``REDACTED`` as a whole, so nothing about it is kept.
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from typing import Any

from agent.env_reference import ENV_VARS

REDACTED = "<redacted>"
MIN_ENV_VALUE_CHARS = 8
"""Shorter sensitive values are only replaced as whole tokens."""

_TOKEN_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.S),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
)
_CREDENTIAL_NAME = r"[\w$]*?(?:password|passwd|secret|token|api_?key|apikey|private_?key|auth|credential)[\w$]*"
_QUOTED = "|".join(
    rf"{q}(?P<v{i}>(?:\\.|[^{q}\\\n]){{6,}}){q}" for i, q in enumerate(('"', "'", "`"))
)
_ASSIGNED_LITERAL = re.compile(
    rf"(?P<name>\b{_CREDENTIAL_NAME}\b[\"']?\s*(?::\s*[\w\[\]<>.,&' ]+?)?\s*(?::=|=|:)\s*)"
    rf"(?P<literal>{_QUOTED})",
    re.I,
)


def sensitive_env_values(environ: Mapping[str, str] | None = None) -> list[str]:
    """The set values of every environment variable registered as sensitive."""
    env = os.environ if environ is None else environ
    values = {env.get(var.name, "") for var in ENV_VARS if var.sensitive}
    return sorted((v for v in values if v), key=len, reverse=True)


def _replace_value(text: str, value: str) -> str:
    # A short value would also hit unrelated substrings, so it only counts as a whole token.
    if len(value) >= MIN_ENV_VALUE_CHARS:
        return text.replace(value, REDACTED)
    return re.sub(rf"(?<![\w-]){re.escape(value)}(?![\w-])", REDACTED, text)


def redact_secrets(text: str, extra_values: Iterable[str] = (), environ: Mapping[str, str] | None = None) -> str:
    """``text`` with sensitive environment values and credential-shaped literals replaced."""
    if not text:
        return text
    values = {*sensitive_env_values(environ), *(v for v in extra_values if v)}
    for value in sorted(values, key=len, reverse=True):
        text = _replace_value(text, value)
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _ASSIGNED_LITERAL.sub(_redact_assigned_literal, text)


def _redact_assigned_literal(match: re.Match[str]) -> str:
    quote = match.group("literal")[0]
    return f"{match.group('name')}{quote}{REDACTED}{quote}"


def redact_value(value: Any, extra_values: Iterable[str] = (), environ: Mapping[str, str] | None = None) -> Any:
    """``value`` with every string inside it (keys included) passed through ``redact_secrets``."""
    extra = list(extra_values)
    if isinstance(value, str):
        return redact_secrets(value, extra, environ)
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            key = redact_value(k, extra, environ)
            # Two keys can redact to the same text; keep both values.
            n = 2
            while key in out:
                key, n = f"{redact_value(k, extra, environ)}#{n}", n + 1
            out[key] = redact_value(v, extra, environ)
        return out
    if isinstance(value, (list, tuple)):
        return type(value)(redact_value(v, extra, environ) for v in value)
    return value
