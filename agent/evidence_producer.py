"""C02 evidence producer-identity route: declared provenance comparison.

`evidence-producer-check` is a consumer route: it reads a declared
`mumei.verification-evidence/v1` record's `provenance` block and a set
of declared producer expectations (CLI flags or the equivalent MCP
arguments), then emits `mumei.evidence-producer-identity/v1` — whether
the record's declared producer fields equal the expectations
(`identity: "match"`) or not (`identity: "mismatch"`, with the
mismatched field names listed).

This discharges the `producer_authenticity` entry of the canonical
`checks_not_performed` vocabulary at representation level only: a match
means the saved record declares THESE producer values, never that the
producer is authentic, the record is valid, fresh-at-acceptance or
true. Full record representation validity stays Core's `evidence
check` duty; the other five semantic checks stay named in
`checks_not_performed`. The route performs no Core call, no fresh
query and no I/O beyond its declared inputs — a foreign or malformed
record is a static error, not an answer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVIDENCE_SCHEMA = "mumei.verification-evidence/v1"
DESCRIPTOR_SCHEMA = "mumei.evidence-producer-identity/v1"
MAX_INPUT_BYTES = 65_536
_HEXDIGITS = frozenset("0123456789abcdef")

_PROVENANCE_REQUIRED = {"adapter", "tool", "configuration_fingerprint"}
_PROVENANCE_OPTIONAL = {"translator_version", "bridge_lemma_hash"}
_ADAPTER_KEYS = {"id", "version", "protocol_version"}
_TOOL_KEYS = {"name", "version"}


def build_producer_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--evidence",
        required=True,
        metavar="PATH",
        help=(
            "Declared verification-evidence record "
            "(mumei.verification-evidence/v1 JSON)."
        ),
    )
    parser.add_argument(
        "--tool",
        required=True,
        metavar="NAME",
        help="Declared expected `provenance.tool.name`.",
    )
    parser.add_argument(
        "--adapter",
        required=True,
        metavar="ID",
        help="Declared expected `provenance.adapter.id`.",
    )
    parser.add_argument(
        "--tool-version",
        metavar="VERSION",
        help=(
            "Declared expected `provenance.tool.version` — when "
            "omitted the version is not compared."
        ),
    )
    parser.add_argument(
        "--adapter-version",
        metavar="VERSION",
        help=(
            "Declared expected `provenance.adapter.version` — when "
            "omitted the version is not compared."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the identity descriptor to PATH instead of stdout.",
    )


def _read_declared_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("declared input exceeds the bounded read limit")
    return data


def _nonempty_str(value: object) -> bool:
    return type(value) is str and bool(value)


def _sha256_str(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and set(value) <= _HEXDIGITS
    )


def _read_evidence_provenance(path: str) -> dict:
    """Restore a record's `provenance` block under the strict shape.

    The closed key sets mirror the v1 contract: `adapter` carries
    exactly `{id, version, protocol_version}`, `tool` exactly
    `{name, version}`, `configuration_fingerprint` is a lowercase
    sha256, and the optional `translator_version`/`bridge_lemma_hash`
    keep their nullable shapes. A foreign or malformed block is a
    declared error, never a mismatch answer.
    """
    raw = _read_declared_bytes(path)
    try:
        value = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise ValueError(
            "declared evidence record is not UTF-8"
        ) from None
    except json.JSONDecodeError:
        raise ValueError(
            "declared evidence record is not JSON"
        ) from None
    if (
        type(value) is not dict
        or value.get("schema_version") != EVIDENCE_SCHEMA
    ):
        raise ValueError("declared evidence record is not the v1 schema")
    provenance = value.get("provenance")
    if type(provenance) is not dict or not set(provenance.keys()) <= (
        _PROVENANCE_REQUIRED | _PROVENANCE_OPTIONAL
    ) or not _PROVENANCE_REQUIRED <= set(provenance.keys()):
        raise ValueError(
            "evidence provenance does not match the declared v1 shape"
        )
    adapter = provenance["adapter"]
    if (
        type(adapter) is not dict
        or set(adapter.keys()) != _ADAPTER_KEYS
        or not all(_nonempty_str(adapter[k]) for k in _ADAPTER_KEYS)
    ):
        raise ValueError(
            "evidence provenance adapter does not match the "
            "declared v1 shape"
        )
    tool = provenance["tool"]
    if (
        type(tool) is not dict
        or set(tool.keys()) != _TOOL_KEYS
        or not all(_nonempty_str(tool[k]) for k in _TOOL_KEYS)
    ):
        raise ValueError(
            "evidence provenance tool does not match the "
            "declared v1 shape"
        )
    if not _sha256_str(provenance["configuration_fingerprint"]):
        raise ValueError(
            "evidence configuration_fingerprint does not match the "
            "declared v1 shape"
        )
    translator = provenance.get("translator_version")
    if translator is not None and not _nonempty_str(translator):
        raise ValueError(
            "evidence translator_version does not match the "
            "declared v1 shape"
        )
    bridge = provenance.get("bridge_lemma_hash")
    if bridge is not None and not _sha256_str(bridge):
        raise ValueError(
            "evidence bridge_lemma_hash does not match the "
            "declared v1 shape"
        )
    return provenance


def compute_producer_descriptor(
    evidence_path: str, expectations: dict[str, str]
) -> dict:
    """Compare a record's `provenance` against declared expectations.

    `expectations` maps dotted provenance fields to declared values:
    `tool.name` and `adapter.id` are always required by the route;
    `tool.version` and `adapter.version` are compared only when
    declared — an omitted expectation never counts as a mismatch.
    Returns the `mumei.evidence-producer-identity/v1` descriptor:
    `identity` is `"match"` when every declared expectation equals
    the record's value, `"mismatch"` otherwise, and `mismatched`
    names the compared fields that differed. Raises
    `ValueError`/`OSError` on any malformed or unreadable declared
    input; callers treat those as static errors, never as a
    mismatch answer.
    """
    provenance = _read_evidence_provenance(evidence_path)
    lookup = {
        "tool.name": provenance["tool"]["name"],
        "tool.version": provenance["tool"]["version"],
        "adapter.id": provenance["adapter"]["id"],
        "adapter.version": provenance["adapter"]["version"],
    }
    unknown = sorted(set(expectations) - set(lookup))
    if unknown:
        raise ValueError(
            "declared expectations name unknown provenance fields: "
            + ", ".join(unknown)
        )
    mismatched = sorted(
        field
        for field, expected in expectations.items()
        if expected is not None and lookup[field] != expected
    )
    return {
        "schema_version": DESCRIPTOR_SCHEMA,
        "evidence_schema_version": EVIDENCE_SCHEMA,
        "tool_name": provenance["tool"]["name"],
        "tool_version": provenance["tool"]["version"],
        "adapter_id": provenance["adapter"]["id"],
        "adapter_version": provenance["adapter"]["version"],
        "identity": "mismatch" if mismatched else "match",
        "mismatched": mismatched,
        "checks_not_performed": [
            "claim_truth",
            "file_identity",
            "freshness",
            "semantic_correspondence",
            "artifact_semantics",
        ],
    }


def main_producer(args: argparse.Namespace | None = None) -> int:
    try:
        output_path = getattr(args, "output", None)
        if output_path is not None:
            out_path = Path(output_path)
            declared = Path(args.evidence)
            try:
                if declared.samefile(out_path):
                    raise ValueError(
                        "--output may not overwrite a declared "
                        "input document"
                    )
            except FileNotFoundError:
                pass
        expectations = {
            "tool.name": args.tool,
            "tool.version": args.tool_version,
            "adapter.id": args.adapter,
            "adapter.version": args.adapter_version,
        }
        descriptor = compute_producer_descriptor(
            args.evidence, expectations
        )
        text = json.dumps(descriptor, indent=2) + "\n"
        if output_path is None:
            sys.stdout.write(text)
        else:
            Path(output_path).write_text(text, encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"evidence-producer-check: {exc}", file=sys.stderr)
        return 1
    return 0
