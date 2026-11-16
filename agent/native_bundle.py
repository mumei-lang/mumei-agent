"""Shared member enumeration for declared native-bundle consumer routes.

`native-recheck` (`recheck-llvm`) and `native-accept`
(`accept-artifact`) fingerprint exactly the bundle members the Core
consumes — which the record itself declares. For a
``mumei.native-bundle/v1`` record that is the ``files`` map's
component members; a ``mumei.native-multifile-bundle/v1`` record
additionally declares every ``sources/<member>`` the merge
re-derivation consumes. Both routes enumerate members through
:func:`declared_members`, so the fingerprint binds the same member set
Core reads for either record family.

Every member name is validated against the Core member grammar
(``/``-separated nonempty segments, none dot-prefixed, no ``\\`` or
``:``, at most 16 segments) BEFORE it joins a path, so a hand-crafted
record cannot steer the fingerprint's file reads outside the bundle.
A record the agent cannot even enumerate is a static error, not a run
— the Core could not read it either. Files present on disk but
undeclared in the record are never fingerprinted: the Core does not
consume them either.
"""

from __future__ import annotations

import json
from pathlib import Path

# Mirrors of the Core side's read bounds (src/commands/native_bundle.rs):
# the pinned record is read under 1 MiB, every component member under
# 32 MiB, each source member under 64 KiB. A declared input the Core
# cannot even read is a static error, not a run.
RECORD_FILE = "native-bundle.json"
MAX_RECORD_BYTES = 1_048_576
MAX_COMPONENT_BYTES = 33_554_432
MAX_SOURCE_BYTES = 65_536

# The `files` map's snake_case keys to bundle-relative names — the same
# table as Core's BundleFile::file_name. An unknown key fails closed:
# the record's member set is the honest enumeration of what the Core
# reads.
FILE_MEMBERS = {
    "llvm_ir": "program.ll",
    "object": "program.o",
    "certificate": "proof-cert.json",
    "executable": "program",
}

# Member-name grammar mirror (mumei-core native_bundle::member_name):
# `/`-separated nonempty segments, none dot-prefixed, no `\\` or `:`,
# at most 16 segments. `.` and `..` segments are covered by the
# dot-prefix rule, so a record cannot steer reads outside `sources/`.
MAX_MEMBER_SEGMENTS = 16


def valid_member_name(name: str) -> bool:
    stem = name[:-3] if name.endswith(".mm") else name
    segments = stem.split("/")
    return bool(stem) and len(segments) <= MAX_MEMBER_SEGMENTS and all(
        segment
        and not segment.startswith(".")
        and "\\" not in segment
        and ":" not in segment
        for segment in segments
    )


def bundle_member_paths(record: dict) -> list[str]:
    """Enumerate the bundle-relative member paths a record declares.

    The `files` map enumerates component members; a `sources` map (the
    multifile family) enumerates original member texts consumed by the
    merge re-derivation. Fail-closed on shapes outside the record
    contract — a record the agent cannot enumerate is a static error
    before any attempt is dispatched.
    """
    files = record.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("native-bundle.json declares no files map")
    members = []
    for key in sorted(files):
        name = FILE_MEMBERS.get(key)
        if name is None:
            raise ValueError(
                f"native-bundle.json declares unknown member {key!r}"
            )
        members.append(name)
    sources = record.get("sources")
    if sources is not None:
        if not isinstance(sources, dict):
            raise ValueError("native-bundle.json sources is not a map")
        for name in sorted(sources):
            if not valid_member_name(name):
                raise ValueError(
                    f"native-bundle.json declares invalid member {name!r}"
                )
            members.append(f"sources/{name}")
    return members


def declared_members(bundle: Path) -> list[str]:
    """Parse the pinned record and enumerate its declared members."""
    record_bytes = (bundle / RECORD_FILE).read_bytes()
    try:
        record = json.loads(record_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"cannot parse {RECORD_FILE}: {exc}") from exc
    if not isinstance(record, dict):
        raise ValueError(f"{RECORD_FILE} is not a JSON object")
    return [RECORD_FILE] + bundle_member_paths(record)


def member_bound_bytes(member: str) -> int:
    """The Core read bound for one declared member."""
    if member == RECORD_FILE:
        return MAX_RECORD_BYTES
    if member.startswith("sources/"):
        return MAX_SOURCE_BYTES
    return MAX_COMPONENT_BYTES
