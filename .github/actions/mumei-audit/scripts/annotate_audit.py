#!/usr/bin/env python3
"""Emit GitHub Actions annotations for active audit findings.

Annotations are a review signal only: they are always ``notice`` severity,
never represent a proof or verification verdict, and never fail the workflow.
Findings suppressed by an adopted baseline are not annotated.
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
from pathlib import Path
from typing import Any

MAX_ANNOTATIONS = 10
MAX_MESSAGE_LENGTH = 500


def _escape_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _load_audit(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _relative_display_path(location: object) -> str:
    """Workspace-relative annotation path, or "" when not safely resolvable."""
    if not isinstance(location, str) or not location:
        return ""
    workspace = (os.environ.get("GITHUB_WORKSPACE") or "").rstrip("/")
    if location.startswith("/"):
        if not workspace or not location.startswith(workspace + "/"):
            return ""
        location = location[len(workspace) + 1 :]
    normalized = posixpath.normpath(location)
    if normalized in ("", ".") or normalized.startswith("..") or normalized.startswith("/"):
        return ""
    return normalized


def _annotation_command(row: dict[str, Any]) -> str:
    message = str(row.get("message", "") or "(no message)")[:MAX_MESSAGE_LENGTH]
    properties = []
    path = _relative_display_path(row.get("source_file"))
    if path:
        properties.append(f"file={_escape_property(path)}")
        line = row.get("line")
        if isinstance(line, int) and not isinstance(line, bool) and line > 0:
            properties.append(f"line={line}")
    prefix = "::notice"
    if properties:
        prefix += " " + ",".join(properties)
    return f"{prefix}::{_escape_data(message)}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-json", required=True)
    args = parser.parse_args()

    audit = _load_audit(Path(args.audit_json))
    findings = audit.get("findings") if isinstance(audit.get("findings"), list) else []
    active = [
        row
        for row in findings
        if isinstance(row, dict) and row.get("baseline") != "suppressed"
    ]
    emitted = 0
    for row in active[:MAX_ANNOTATIONS]:
        print(_annotation_command(row))
        emitted += 1
    remaining = len(active) - emitted
    if remaining > 0:
        print(
            "::notice::"
            + _escape_data(
                f"{remaining} more active findings not annotated; see the audit evidence artifact and step summary."
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
