"""Build migration-execution acceptance artifacts from audit migration hints."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from agent.audit_models import AuditDirectoryResult, AuditResult
from agent.migration_readiness import (
    _contract_health,
    _diagnostics,
    _effect_profile,
    _hint_file_result,
    _read_source,
    _source_payload,
    _verification_feasibility,
)
from agent.audit_reporting import _safe_identifier
from agent.secret_redaction import redact_secrets

SCHEMA = "mumei.migration-execution/v1"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _sha256_file(path: Path) -> str | None:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError:
        return None


def _write_json_atomic(output_path: Path, report: dict[str, object]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=output_path.name + ".", dir=output_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output_file:
            output_file.write(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        if output_path.is_file() and not output_path.is_symlink():
            os.chmod(temporary_name, output_path.stat().st_mode & 0o777)
        os.replace(temporary_name, output_path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _write_text_exclusive(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8") as output_file:
        output_file.write(text)


def _safe_stem(function_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", function_name).strip("._-") or "migration_candidate"


def _strip_mm_comments(source: str, *, mask_strings: bool) -> list[str]:
    """``.mm`` lines without line comments, optionally with string contents masked."""
    in_string = False
    code_lines: list[str] = []
    for line in source.splitlines():
        out: list[str] = []
        index = 0
        while index < len(line):
            char = line[index]
            if in_string:
                if char == "\\" and index + 1 < len(line):
                    if not mask_strings:
                        out.append(line[index : index + 2])
                    index += 2
                    continue
                if char == '"':
                    in_string = False
                if not mask_strings or char == '"':
                    out.append(char)
                index += 1
                continue
            if char == "/" and index + 1 < len(line) and line[index + 1] == "/":
                break
            if char == '"':
                in_string = True
            out.append(char)
            index += 1
        code_lines.append("".join(out))
    return code_lines


def _outside_string_mask(code: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    for char in code:
        if in_string:
            out.append("\n" if char == "\n" else " ")
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


_CREDENTIAL_WORD = r"[\w$]*(?:password|passwd|secret|token|api_?key|apikey|private_?key|auth|credential)[\w$]*"
_CREDENTIAL_EXPR = rf"(?:[\w$]+\.)*{_CREDENTIAL_WORD}"
_STRING_LITERAL = r'"(?:\\.|[^"\\])*"'
_OPEN_PARENS = r"(?:\(\s*)*"
_CLOSE_PARENS = r"(?:\s*\))*"
_PAREN_CREDENTIAL_EXPR = rf"{_OPEN_PARENS}{_CREDENTIAL_EXPR}{_CLOSE_PARENS}"
_CREDENTIAL_NAME_PATTERN = rf"(?<![\w$])(?P<name>{_PAREN_CREDENTIAL_EXPR})(?![\w$])"
_CREDENTIAL_COMPARISON_FORWARD = re.compile(
    rf"{_CREDENTIAL_NAME_PATTERN}\s*(?P<op>==|!=)\s*{_OPEN_PARENS}(?P<literal>{_STRING_LITERAL})",
    re.IGNORECASE,
)
_CREDENTIAL_COMPARISON_REVERSE = re.compile(
    rf"{_OPEN_PARENS}(?P<literal>{_STRING_LITERAL}){_CLOSE_PARENS}\s*(?P<op>==|!=)\s*{_CREDENTIAL_NAME_PATTERN}",
    re.IGNORECASE,
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    rf"{_CREDENTIAL_NAME_PATTERN}\s*(?::=|=(?!=))\s*{_OPEN_PARENS}(?P<literal>{_STRING_LITERAL})",
    re.IGNORECASE,
)


def _redact_credential_comparison_literals(text: str) -> str:
    spans: list[tuple[int, int]] = []
    for pattern in (_CREDENTIAL_COMPARISON_FORWARD, _CREDENTIAL_COMPARISON_REVERSE, _CREDENTIAL_ASSIGNMENT):
        spans.extend((match.start("literal"), match.end("literal")) for match in pattern.finditer(text))
    if not spans:
        return text
    out: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        if start < cursor:
            continue
        out.append(text[cursor:start])
        out.append('"<redacted>"')
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def redact_sensitive_migration_text(text: str) -> str:
    return _redact_credential_comparison_literals(redact_secrets(text))


def migration_text_has_sensitive_literals(text: str) -> bool:
    return redact_sensitive_migration_text(text) != text


def _extract_mm_clauses(code: str, keyword: str) -> list[str]:
    clauses: list[str] = []
    outside_strings = _outside_string_mask(code)
    for match in re.finditer(rf"\b{keyword}\s*:", outside_strings):
        index = match.end()
        start = index
        in_string = False
        while index < len(code):
            char = code[index]
            if in_string:
                if char == "\\":
                    index += 2
                    continue
                if char == '"':
                    in_string = False
                index += 1
                continue
            if char == '"':
                in_string = True
                index += 1
                continue
            if char == ";":
                clauses.append(code[start:index].strip())
                break
            index += 1
    return clauses


def _extracted_contract(skeleton: str) -> dict[str, object]:
    code = "\n".join(_strip_mm_comments(skeleton, mask_strings=False))
    masked = "\n".join(_strip_mm_comments(skeleton, mask_strings=True))
    raw_requires = _extract_mm_clauses(code, "requires")
    raw_ensures = _extract_mm_clauses(code, "ensures")
    requires = [redact_sensitive_migration_text(item) for item in raw_requires]
    ensures = [redact_sensitive_migration_text(item) for item in raw_ensures]
    trusted_atoms = re.findall(r"\btrusted\s+atom\s+([A-Za-z_]\w*)", masked)
    weak = bool(requires and ensures and all(item == "true" for item in requires + ensures))
    string_literals_present = any(re.search(_STRING_LITERAL, item) for item in raw_requires + raw_ensures)
    return {
        "requires": requires,
        "ensures": ensures,
        "weak_true_contract": weak,
        "trusted_atom_declarations": trusted_atoms,
        "string_literals_present": string_literals_present,
        "string_literals_redacted": any('"<redacted>"' in item for item in requires + ensures),
        "generated_contract_sha256": _sha256_text(skeleton),
    }


def _candidate_source(result: AuditResult | AuditDirectoryResult, hint: dict[str, object], occurrence: int, default_path: str, default_language: str) -> tuple[AuditResult | AuditDirectoryResult, str, str]:
    file_result = _hint_file_result(result, hint, occurrence)
    if file_result is None:
        return result, default_path, default_language
    return file_result, file_result.source_file, file_result.language


def migration_output_key(source_path: str | Path, skeleton: str) -> str:
    source_identity = str(Path(source_path).expanduser().resolve())
    return _sha256_text(source_identity + "\0" + skeleton)[:12]


def migration_output_target(output_dir: Path, source_path: str | Path, function_name: str, skeleton: str) -> Path:
    key = migration_output_key(source_path, skeleton)
    candidate = output_dir / f"{function_name}-{key}.mm"
    if not candidate.exists() and not candidate.is_symlink():
        return candidate
    suffix = 1
    while True:
        candidate = output_dir / f"{function_name}-{key}-{suffix}.mm"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        suffix += 1


def _canonical_mm_text(text: str) -> str:
    return text.rstrip() + "\n" if text.strip() else text


_ABSOLUTE_PATH_FRAGMENT = re.compile(r"(?<![\w])(?:/[^\s:;,()\[\]{}'\"]+)+")


def _redact_error_text(text: str) -> str:
    return redact_secrets(_ABSOLUTE_PATH_FRAGMENT.sub("<path>", str(text)))


def _healed_content(function_name: str, healed_files: list[str], skeleton: str, source_path: str, excluded_paths: set[str]) -> tuple[str, str | None, bool]:
    base_names = {function_name, _safe_stem(function_name), _safe_identifier(function_name)}
    expected_names = {f"{base}.mm" for base in base_names}
    key = migration_output_key(source_path, skeleton)

    def matches(path: Path) -> bool:
        if not path.is_file():
            return False
        if path.name in expected_names:
            return True
        return any(
            re.fullmatch(rf"{re.escape(base)}-{key}(?:-\d+)?\.mm", path.name) is not None
            for base in base_names
        )

    matches = [Path(healed) for healed in healed_files if str(Path(healed)) not in excluded_paths and matches(Path(healed))]
    try:
        source_parent = Path(source_path).expanduser().resolve().parent
        preferred = [path for path in matches if path.expanduser().resolve().parent == source_parent]
    except OSError:
        preferred = []
    if len(preferred) == 1:
        matches = preferred
    if len(matches) != 1:
        return skeleton, None, False
    path = matches[0]
    try:
        return path.read_text(encoding="utf-8"), str(path), True
    except OSError:
        return skeleton, str(path), False


def _behavior_entries(file_result: AuditResult | AuditDirectoryResult, function_name: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    if not isinstance(file_result, AuditResult):
        return entries

    def matches(value: object) -> bool:
        text = str(value or "")
        if text == function_name:
            return True
        leaf = function_name.split(".")[-1]
        if "." in text or text != leaf:
            return False
        same_leaf_hints = [
            str(hint.get("function_name") or "")
            for hint in file_result.migration_hints
            if isinstance(hint, dict) and str(hint.get("function_name") or "").split(".")[-1] == leaf
        ]
        return same_leaf_hints == [function_name]

    for item in file_result.native_replays:
        if isinstance(item, dict) and matches(item.get("function") or item.get("function_name") or item.get("atom")):
            entries.append(
                {
                    "kind": "native_replay",
                    "function_name": function_name,
                    "input": item.get("input"),
                    "outcome": item.get("verdict"),
                    "reason": item.get("reason"),
                    "source": item.get("source"),
                }
            )
    for item in file_result.body_ports:
        if isinstance(item, dict) and matches(item.get("function") or item.get("function_name") or item.get("atom")):
            entries.append(
                {
                    "kind": "body_port",
                    "function_name": function_name,
                    "outcome": item.get("outcome"),
                    "reason": item.get("reason"),
                    "counterexample": item.get("counterexample"),
                }
            )
    serialized = json.dumps(entries, ensure_ascii=False, sort_keys=True, default=str)
    redacted = redact_secrets(serialized)
    return json.loads(redacted)[:10]


def _verify_generated_mm(
    *,
    mm_path: Path,
    artifact_dir: Path,
    mumei_client,
) -> dict[str, object]:
    proof_path = mm_path.with_suffix(".proof.json")
    verify_dir = artifact_dir / mm_path.stem
    verify_dir.mkdir(parents=True, exist_ok=True)
    sarif_path = verify_dir / "report.sarif"
    verification: dict[str, object] = {
        "attempted": False,
        "status": "unavailable" if mumei_client is None else "not_attempted",
        "diagnostics": [],
        "operational_error": None,
        "contract_proved": False,
        "sarif": {"path": str(sarif_path), "sha256": None, "written": False},
        "proof_certificate": {"path": str(proof_path), "sha256": None, "written": False},
    }
    if mumei_client is None:
        verification["operational_error"] = "VerifierUnavailable"
        verification["diagnostics"] = ["mumei verifier client is unavailable"]
        return verification
    verification["attempted"] = True
    try:
        result = mumei_client.verify(
            str(mm_path),
            report_dir=str(verify_dir),
            extra_args=["--emit", "sarif", "--proof-cert", "--output", str(proof_path)],
        )
    except Exception as exc:
        verification["status"] = "operational_error"
        verification["operational_error"] = type(exc).__name__
        verification["diagnostics"] = [type(exc).__name__]
        return verification
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    if not report:
        verification["status"] = "operational_error"
        verification["operational_error"] = "VerifierOutputUnavailable"
        verification["diagnostics"] = ["mumei verify did not produce a machine-readable report"]
        return verification
    verification.update(
        {
            "success": result.get("success") is True,
            "status": report.get("status") or ("verified" if result.get("success") is True else "failed"),
            "diagnostics": _diagnostics(
                result,
                (artifact_dir, verify_dir, mm_path, proof_path, artifact_dir.resolve(), verify_dir.resolve(), mm_path.resolve(), proof_path.resolve()),
            ),
        }
    )
    status = verification.get("status")
    verification["contract_proved"] = result.get("success") is True and status in {"success", "verified", "pass", "passed"}
    verification["proof_certificate"] = {
        "path": str(proof_path),
        "sha256": _sha256_file(proof_path),
        "written": proof_path.is_file(),
    }
    verification["sarif"] = {
        "path": str(sarif_path),
        "sha256": _sha256_file(sarif_path),
        "written": sarif_path.is_file(),
    }
    return verification


def _write_partial(output_path: Path, report: dict[str, object]) -> None:
    _write_json_atomic(output_path, report)


def build_migration_execution(
    result: AuditResult | AuditDirectoryResult,
    *,
    output_path: Path,
    mumei_client=None,
    selected_functions: list[str] | None = None,
    heal_attempted: bool = False,
) -> dict[str, object]:
    """Build and write the additive migration-execution acceptance artifact."""
    source_path, language, source_kind = _source_payload(result)
    artifact_base = output_path.parent / f"{output_path.stem}.migration-execution"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir = artifact_base
    index = 0
    while artifact_dir == output_path or artifact_dir.exists() or artifact_dir.is_symlink():
        index += 1
        artifact_dir = output_path.parent / f"{output_path.stem}.migration-execution-{index}"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / ".mumei-generated-artifacts").write_text("generated by mumei-agent migration execution\n", encoding="utf-8")

    requested = list(dict.fromkeys(selected_functions or []))
    requested_set = set(requested)
    report: dict[str, object] = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "path": source_path,
            "language": language,
            "kind": source_kind,
            "sha256": _sha256_file(Path(source_path)) if source_kind == "file" else None,
        },
        "audit": {
            "success": result.success,
            "verification_status": result.verification_status,
            "finding_counts": result.finding_counts,
            "migration_candidate_count": len(result.migration_hints),
        },
        "selection": {
            "basis": "explicit migration_function values" if requested else "all audit migration_hints candidates",
            "requested_functions": requested,
            "missing_requested_functions": [],
        },
        "candidates": [],
        "operational_errors": [],
        "summary": {
            "candidate_count": 0,
            "ready_for_human_review": 0,
            "blocked": 0,
            "operational_error": 0,
            "review_required": False,
        },
        "artifact_paths": {"migration_execution": str(output_path), "generated_artifacts": str(artifact_dir)},
        "evidence_boundary": [
            "A verified generated .mm skeleton proves only the skeleton contract as written; it is not proof that host-language code implements the same behavior.",
            "Behavioral replay, native execution, and body-port entries are diagnostic evidence only and are not semantic-equivalence proof or formal verdicts.",
            "Weak true/true contracts and trusted atom declarations remain blockers for human review even when verification succeeds.",
            "Credential-like comparison/assignment literals, known token formats, and environment secret values are redacted in recorded contract clauses and block generated .mm artifact copying; non-secret string literals remain diagnostic contract content.",
        ],
    }
    _write_partial(output_path, report)

    occurrences: dict[tuple[str, str], int] = {}
    claimed_healed_files: set[str] = set()
    missing = set(requested)
    for hint_index, hint in enumerate(result.migration_hints):
        if not isinstance(hint, dict):
            continue
        function_name = str(hint.get("function_name") or "unknown")
        if requested_set and function_name not in requested_set and function_name.split(".")[-1] not in requested_set:
            continue
        missing.discard(function_name)
        missing.discard(function_name.split(".")[-1])
        occurrence_key = (function_name, str(hint.get("skeleton") or ""))
        occurrence = occurrences.get(occurrence_key, 0)
        occurrences[occurrence_key] = occurrence + 1
        file_result, hint_source, hint_language = _candidate_source(result, hint, occurrence, source_path, language)
        skeleton = str(hint.get("skeleton") or "")
        source_text = _read_source(hint_source)
        health = _contract_health(file_result)
        effects = _effect_profile(source_text, hint_language, function_name)
        feasibility, feasibility_blockers = _verification_feasibility(hint, health, effects)
        source_hash = _sha256_file(Path(hint_source))
        candidate: dict[str, object] = {
            "function_name": function_name,
            "source_provenance": {
                "path": hint_source,
                "language": hint_language,
                "sha256": source_hash,
                "audit_priority": str(hint.get("priority") or "review"),
                "migration_hint_index": hint_index,
            },
            "selection": {"selected": True, "reason": redact_secrets(str(hint.get("reason") or ""))},
            "extracted_contract": _extracted_contract(skeleton),
            "generated_mm": {"path": None, "sha256": None, "origin": "generated_skeleton", "healed_source_path": None},
            "heal": {"attempted": heal_attempted, "errors": [], "healed_file": None},
            "verification": {},
            "unbound_audit_diagnostics": {
                "status": "not_available",
                "reason": "audit did not produce native-replay or body-port diagnostics for this function",
                "semantics": "diagnostic evidence only; not semantic-equivalence proof",
                "binding": {
                    "status": "not_bound_to_generated_mm",
                    "generated_mm_sha256": None,
                    "reason": "entries come from host-code audit lanes, not execution of the generated/healed .mm artifact",
                },
                "entries": [],
            },
            "contract_provenance": {},
            "evidence_blockers": [
                item
                for item in feasibility_blockers
                if item != "generated skeleton has weak true/true contracts"
            ],
            "operational_errors": [],
            "review_required": True,
            "execution_state": "not_attempted",
        }
        report["candidates"].append(candidate)
        _write_partial(output_path, report)
        try:
            healed_text, healed_path, used_healed = _healed_content(function_name, result.healed_files, skeleton, hint_source, claimed_healed_files)
            if healed_path is not None:
                claimed_healed_files.add(healed_path)
                candidate["heal"]["healed_file"] = healed_path
                candidate["generated_mm"]["origin"] = "healed_file" if used_healed else "generated_skeleton"
            heal_errors = file_result.heal_errors if isinstance(file_result, AuditResult) else result.heal_errors
            expected_error_stems = {function_name, _safe_stem(function_name), _safe_identifier(function_name)}
            error_key = migration_output_key(hint_source, skeleton)

            def heal_error_matches(item: object) -> bool:
                text = str(item)
                if text.startswith(f"{function_name}:"):
                    return True
                stem = Path(text.split(":", 1)[0]).stem
                if stem in expected_error_stems:
                    return True
                return any(
                    re.fullmatch(rf"{re.escape(base)}-{error_key}(?:-\d+)?", stem) is not None
                    for base in expected_error_stems
                )

            candidate["heal"]["errors"] = [
                _redact_error_text(item)
                for item in heal_errors
                if heal_error_matches(item)
            ]
            candidate["heal"]["attempted"] = heal_attempted or healed_path is not None or bool(candidate["heal"]["errors"])
            if candidate["heal"]["errors"]:
                candidate["evidence_blockers"].append("heal completed with errors")
            original_text = _canonical_mm_text(skeleton)
            final_text = _canonical_mm_text(healed_text)
            contract = _extracted_contract(final_text)
            original_contract = _extracted_contract(original_text)
            candidate["extracted_contract"] = contract
            candidate["contract_provenance"] = {
                "original_skeleton_sha256": _sha256_text(original_text),
                "original_requires": original_contract["requires"],
                "original_ensures": original_contract["ensures"],
                "final_sha256": _sha256_text(final_text),
                "final_requires": contract["requires"],
                "final_ensures": contract["ensures"],
                "content_changed": final_text != original_text,
                "contract_clauses_changed": (
                    original_contract["requires"] != contract["requires"]
                    or original_contract["ensures"] != contract["ensures"]
                ),
            }
            behavior_entries = _behavior_entries(file_result, function_name)
            candidate["unbound_audit_diagnostics"] = {
                "status": "available" if behavior_entries else "not_available",
                "reason": None if behavior_entries else "audit did not produce native-replay or body-port diagnostics for this function",
                "semantics": "diagnostic evidence only; not semantic-equivalence proof",
                "binding": {
                    "status": "not_bound_to_generated_mm",
                    "generated_mm_sha256": None,
                    "reason": "entries come from host-code audit lanes, not execution of the generated/healed .mm artifact",
                },
                "entries": behavior_entries,
            }
            if not final_text.strip():
                candidate["evidence_blockers"].append("generated .mm content is empty")
                candidate["execution_state"] = "blocked"
                _write_partial(output_path, report)
                continue
            if migration_text_has_sensitive_literals(final_text):
                candidate["evidence_blockers"].append("generated .mm contains sensitive credential-shaped data; artifact generation suppressed")
                candidate["execution_state"] = "blocked"
                _write_partial(output_path, report)
                continue
            stem = _safe_stem(function_name) + "-" + _sha256_text(final_text)[:12]
            mm_path = artifact_dir / f"{stem}.mm"
            suffix = 1
            while mm_path.exists():
                mm_path = artifact_dir / f"{stem}-{suffix}.mm"
                suffix += 1
            _write_text_exclusive(mm_path, final_text)
            candidate["generated_mm"].update(
                {
                    "path": str(mm_path),
                    "sha256": _sha256_file(mm_path),
                    "healed_source_path": healed_path,
                }
            )
            verification = _verify_generated_mm(mm_path=mm_path, artifact_dir=artifact_dir, mumei_client=mumei_client)
            candidate["verification"] = verification
            if verification.get("operational_error"):
                candidate["operational_errors"].append(verification["operational_error"])
            elif verification.get("contract_proved") is not True:
                candidate["evidence_blockers"].append(f"generated .mm verification status is {verification.get('status')}")
            proof = verification.get("proof_certificate") if isinstance(verification.get("proof_certificate"), dict) else {}
            if verification.get("attempted") and not proof.get("written"):
                candidate["evidence_blockers"].append("proof certificate was not written")
            if contract["weak_true_contract"]:
                candidate["evidence_blockers"].append("generated skeleton has weak true/true contracts")
            if contract["trusted_atom_declarations"]:
                candidate["evidence_blockers"].append("generated .mm declares trusted atoms")
            candidate["evidence_blockers"] = list(dict.fromkeys(str(item) for item in candidate["evidence_blockers"]))
            if candidate["operational_errors"]:
                candidate["execution_state"] = "operational_error"
            elif candidate["evidence_blockers"]:
                candidate["execution_state"] = "blocked"
            else:
                candidate["execution_state"] = "ready_for_human_review"
        except Exception as exc:
            candidate["operational_errors"].append(type(exc).__name__)
            candidate["execution_state"] = "operational_error"
            report["operational_errors"].append(f"{function_name}: {type(exc).__name__}")
        _write_partial(output_path, report)

    report["selection"]["missing_requested_functions"] = sorted(missing)
    report["summary"] = {
        "candidate_count": len(report["candidates"]),
        "ready_for_human_review": sum(1 for item in report["candidates"] if item.get("execution_state") == "ready_for_human_review"),
        "blocked": sum(1 for item in report["candidates"] if item.get("execution_state") == "blocked"),
        "operational_error": sum(1 for item in report["candidates"] if item.get("execution_state") == "operational_error"),
        "review_required": bool(report["candidates"] or missing),
    }
    _write_partial(output_path, report)
    return report


def append_execution_next_step(result: AuditResult | AuditDirectoryResult, report: dict[str, object], output_path: Path) -> None:
    """Expose migration execution through the fixed human-review handoff key."""
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    action = (
        "migration execution evidence を確認: "
        f"ready {summary.get('ready_for_human_review', 0)}, blocked {summary.get('blocked', 0)}, "
        f"operational errors {summary.get('operational_error', 0)}; report: {output_path}"
    )
    step = {
        "priority": "high" if summary.get("blocked") or summary.get("operational_error") else "medium",
        "action": action,
        "command": "",
        "migration_execution_report": str(output_path),
    }
    if not any(existing.get("migration_execution_report") == str(output_path) for existing in result.next_steps):
        result.next_steps.append(step)
