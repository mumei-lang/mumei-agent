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
_ASSIGNED_LITERAL = re.compile(
    rf"(?P<name>\b{_CREDENTIAL_NAME}\b[\"']?\s*(?::\s*[\w\[\]<>.,&' ]+?)?\s*(?::=|=|:)\s*)"
    r"(?P<quote>[\"'`])(?P<value>[^\"'`\n]{6,})(?P=quote)",
    re.I,
)


def sensitive_env_values(environ: Mapping[str, str] | None = None) -> list[str]:
    """The set values of every environment variable registered as sensitive."""
    env = os.environ if environ is None else environ
    values = {env.get(var.name, "") for var in ENV_VARS if var.sensitive}
    return sorted((v for v in values if len(v) >= MIN_ENV_VALUE_CHARS), key=len, reverse=True)


def redact_secrets(text: str, extra_values: Iterable[str] = (), environ: Mapping[str, str] | None = None) -> str:
    """``text`` with sensitive environment values and credential-shaped literals replaced."""
    if not text:
        return text
    for value in [*sensitive_env_values(environ), *(v for v in extra_values if len(v) >= MIN_ENV_VALUE_CHARS)]:
        text = text.replace(value, REDACTED)
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _ASSIGNED_LITERAL.sub(_redact_assigned_literal, text)


def _redact_assigned_literal(match: re.Match[str]) -> str:
    quote = match.group("quote")
    return f"{match.group('name')}{quote}{REDACTED}{quote}"


def redact_value(value: Any, extra_values: Iterable[str] = (), environ: Mapping[str, str] | None = None) -> Any:
    """``value`` with every string inside it (keys included) passed through ``redact_secrets``."""
    extra = list(extra_values)
    if isinstance(value, str):
        return redact_secrets(value, extra, environ)
    if isinstance(value, dict):
        return {redact_value(k, extra, environ): redact_value(v, extra, environ) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact_value(v, extra, environ) for v in value)
    return value
