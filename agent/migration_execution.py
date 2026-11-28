"""Build migration-execution acceptance artifacts from audit migration hints."""
from __future__ import annotations

import ast
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


_STRING_LITERAL = r'"(?:\\.|[^"\\])*"'
_MASKED_STRING = r"__MUMEI_STRING_\d+__"
_TOKEN_RE = re.compile(
    rf"(?P<string>{_MASKED_STRING})"
    r"|(?P<boolop>&&|\|\|)"
    r"|(?P<op>==|!=|:=|=)"
    r"|(?P<name>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)"
    r"|(?P<punct>[(){};:,])"
    r"|(?P<space>\s+)"
    r"|(?P<other>.)"
)
_OPERAND_SEPARATORS = {";", ",", ":", "{", "}"}


def _mask_string_literals(text: str) -> tuple[str, dict[str, tuple[int, int]]]:
    out: list[str] = []
    mapping: dict[str, tuple[int, int]] = {}
    index = 0
    count = 0
    while index < len(text):
        if text[index] != '"':
            out.append(text[index])
            index += 1
            continue
        start = index
        index += 1
        escaped = False
        closed = False
        while index < len(text):
            char = text[index]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                closed = True
                break
            index += 1
        end = index + 1 if closed else len(text)
        placeholder = f"__MUMEI_STRING_{count}__"
        mapping[placeholder] = (start, end)
        out.append(placeholder)
        count += 1
        index = end
    return "".join(out), mapping


def _lex_masked_text(masked: str) -> list[tuple[str, str]]:
    return [
        (match.lastgroup or "other", match.group())
        for match in _TOKEN_RE.finditer(masked)
        if match.lastgroup != "space"
    ]


def _is_boolean_separator(token: tuple[str, str]) -> bool:
    return token[0] == "boolop" or (token[0] == "name" and token[1].lower() in {"and", "or"})


def _operand_before(tokens: list[tuple[str, str]], operator_index: int) -> list[tuple[str, str]]:
    start = 0
    depth = 0
    for index in range(operator_index - 1, -1, -1):
        value = tokens[index][1]
        if value == ")":
            depth += 1
            continue
        if value == "(":
            if depth == 0:
                start = index + 1
                break
            depth -= 1
            continue
        if depth == 0 and (value in _OPERAND_SEPARATORS or _is_boolean_separator(tokens[index])):
            start = index + 1
            break
    return tokens[start:operator_index]


def _operand_after(tokens: list[tuple[str, str]], operator_index: int) -> list[tuple[str, str]]:
    end = len(tokens)
    for index in range(operator_index + 1, len(tokens)):
        if tokens[index][1] in _OPERAND_SEPARATORS or _is_boolean_separator(tokens[index]):
            end = index
            break
    return tokens[operator_index + 1:end]


def _trim_grouping(tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
    trimmed = list(tokens)
    while trimmed and (
        trimmed[0][1] in {"(", "!"}
        or (trimmed[0][0] == "name" and trimmed[0][1].lower() == "not")
    ):
        trimmed.pop(0)
    while trimmed and trimmed[-1][1] == ")":
        trimmed.pop()
    return trimmed


def _simple_token(tokens: list[tuple[str, str]], kind: str) -> tuple[str, str] | None:
    trimmed = _trim_grouping(tokens)
    if len(trimmed) == 1 and trimmed[0][0] == kind:
        return trimmed[0]
    return None


def _is_credential_name(value: str) -> bool:
    credential_words = {"password", "passwd", "secret", "token", "auth", "authentication", "credential", "credentials", "apikey", "privatekey", "accesskey", "sessionkey", "signingkey", "encryptionkey"}
    compound_suffixes = {"value", "hash", "digest", "key", "accesskey", "token", "secret", "password", "passwd", "credential", "credentials", "code", "store"}
    numeric_compound_roots = {"password", "passwd", "secret", "token", "credential", "apikey", "privatekey", "accesskey", "sessionkey"}
    key_pairs = {("api", "key"), ("private", "key"), ("access", "key"), ("session", "key"), ("signing", "key"), ("encryption", "key")}
    dot_components = value.split(".")
    key_contexts = {"access", "session", "signing", "encryption", "private", "api", "client"}
    if len(dot_components) > 1 and dot_components[-1].lower() == "key" and dot_components[-2].lower() in key_contexts:
        return True
    weak_root_prefixes = {"access", "refresh", "bearer", "session", "api", "client", "user", "service", "app", "auth", "authentication", "oauth", "csrf", "xsrf", "id", "signing", "encryption", "private"}
    for component in dot_components:
        component_words: list[str] = []
        for part in re.split(r"[_$\-]+", component):
            lowered_part = part.lower()
            if re.fullmatch(r"(?:api[_-]?key|private[_-]?key)", part, re.IGNORECASE):
                return True
            for root in credential_words:
                position = lowered_part.find(root)
                while position >= 0:
                    remainder = lowered_part[position + len(root):]
                    prefix = lowered_part[:position]
                    weak_blocked = root in {"auth", "authentication"} and prefix and prefix not in weak_root_prefixes
                    if not weak_blocked and (not remainder or remainder in compound_suffixes or (root in numeric_compound_roots and remainder.isdigit())):
                        return True
                    position = lowered_part.find(root, position + 1)
            component_words.extend(match.group(0).lower() for match in re.finditer(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", part))
        if any(word in credential_words for word in component_words):
            return True
        if any(pair in key_pairs for pair in zip(component_words, component_words[1:])):
            return True
    return False

def _is_credential_operand(tokens: list[tuple[str, str]]) -> bool:
    token = _simple_token(tokens, "name")
    return token is not None and _is_credential_name(token[1])


def _string_operand(tokens: list[tuple[str, str]]) -> str | None:
    token = _simple_token(tokens, "string")
    return token[1] if token is not None else None


def _redact_credential_comparison_literals(text: str) -> str:
    masked, mapping = _mask_string_literals(text)
    tokens = _lex_masked_text(masked)
    placeholders: set[str] = set()
    for index, token in enumerate(tokens):
        if token[0] != "op":
            continue
        before = _operand_before(tokens, index)
        after = _operand_after(tokens, index)
        left_string = _string_operand(before)
        right_string = _string_operand(after)
        if token[1] in {"==", "!="}:
            if _is_credential_operand(before) and right_string is not None:
                placeholders.add(right_string)
            if left_string is not None and _is_credential_operand(after):
                placeholders.add(left_string)
        elif token[1] in {"=", ":="} and _is_credential_operand(before) and right_string is not None:
            placeholders.add(right_string)
    spans = sorted(mapping[placeholder] for placeholder in placeholders if placeholder in mapping)
    if not spans:
        return text
    out: list[str] = []
    cursor = 0
    for start, end in spans:
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


def _normalize_conjunct_text(text: str) -> str:
    out: list[str] = []
    in_string = False
    pending_space = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < len(text):
                index += 1
                out.append(text[index])
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            if pending_space and out:
                out.append(" ")
            pending_space = False
            in_string = True
            out.append(char)
        elif char.isspace():
            pending_space = bool(out)
        else:
            if pending_space:
                out.append(" ")
            pending_space = False
            out.append(char)
        index += 1
    return "".join(out).strip()


def _has_top_level_or(text: str) -> bool:
    depth = 0
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and text.startswith("||", index):
            return True
        index += 1
    return False


def _normalized_top_level_conjuncts(clauses: list[str]) -> list[str]:
    parts: list[str] = []
    for clause in clauses:
        if _has_top_level_or(clause):
            parts.append(_normalize_conjunct_text(clause))
            continue
        start = 0
        index = 0
        depth = 0
        in_string = False
        while index < len(clause):
            char = clause[index]
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
            elif char in "([{":
                depth += 1
            elif char in ")]}":
                depth = max(0, depth - 1)
            elif depth == 0 and clause.startswith("&&", index):
                parts.append(_normalize_conjunct_text(clause[start:index]))
                index += 2
                start = index
                continue
            index += 1
        parts.append(_normalize_conjunct_text(clause[start:]))
    return [part for part in parts if part]


def _conjunct_delta(original: list[str], final: list[str]) -> dict[str, list[str]]:
    original_parts = _normalized_top_level_conjuncts(original)
    final_parts = _normalized_top_level_conjuncts(final)
    remaining = list(original_parts)
    added: list[str] = []
    for part in final_parts:
        if part in remaining:
            remaining.remove(part)
        else:
            added.append(part)
    return {"added": sorted(added), "removed": sorted(remaining)}


def _initial_contract_erosion(reason: str) -> dict[str, object]:
    return {
        "status": "not_checked",
        "checked": False,
        "reason": reason,
        "summary": None,
        "source": "migration_execution_core_recheck",
        "atom_count": 0,
        "eroded_atom_count": 0,
        "atoms": [],
    }


def _contract_erosion_check(original_text: str, final_text: str, *, mumei_client) -> dict[str, object]:
    if final_text == original_text:
        result = _initial_contract_erosion("contract text is unchanged")
        result["status"] = "skipped_no_change"
        return result
    if mumei_client is None or not hasattr(mumei_client, "erosion_check"):
        result = _initial_contract_erosion("mumei erosion check is unavailable")
        result["status"] = "unavailable"
        return result
    if migration_text_has_sensitive_literals(original_text) or migration_text_has_sensitive_literals(final_text):
        result = _initial_contract_erosion("sensitive contract content suppressed before erosion comparison")
        return result

    try:
        with tempfile.TemporaryDirectory(prefix="mumei-migration-erosion-") as temp_dir:
            temp_path = Path(temp_dir)
            baseline_path = temp_path / "baseline.mm"
            candidate_path = temp_path / "candidate.mm"
            baseline_path.write_text(original_text, encoding="utf-8")
            candidate_path.write_text(final_text, encoding="utf-8")
            outcome = mumei_client.erosion_check(str(candidate_path), str(baseline_path))
    except Exception as exc:
        result = _initial_contract_erosion("erosion check raised before a structured result was available")
        result["status"] = "operational_error"
        result["summary"] = type(exc).__name__
        return result

    if not isinstance(outcome, dict):
        result = _initial_contract_erosion("erosion check returned no structured result")
        result["status"] = "malformed"
        return result
    returncode = outcome.get("returncode")
    report = outcome.get("report")
    if returncode == 2:
        result = _initial_contract_erosion("mumei erosion check is unavailable in this toolchain")
        result["status"] = "unavailable"
        return result
    if returncode == 4:
        result = _initial_contract_erosion("original or final contract text could not be checked")
        result["status"] = "malformed"
        return result
    if not isinstance(report, dict) or not isinstance(report.get("atoms"), list):
        result = _initial_contract_erosion("erosion check did not return a structured erosion report")
        result["status"] = "malformed"
        return result

    atoms = []
    hard_failure = False
    inconclusive = False
    eroded = 0
    hard_statuses = {"pre_weakened", "post_weakened", "missing", "signature_mismatch", "trust_added", "effects_widened"}
    for atom in report["atoms"][:20]:
        if not isinstance(atom, dict):
            continue
        status = str(atom.get("status") or "unknown")
        name = redact_secrets(str(atom.get("name") or "<unknown>"))
        atoms.append({"name": name, "status": status})
    for atom in report["atoms"]:
        if not isinstance(atom, dict):
            continue
        status = str(atom.get("status") or "")
        if status in hard_statuses:
            hard_failure = True
            eroded += 1
        elif status == "inconclusive":
            inconclusive = True
            eroded += 1

    result = _initial_contract_erosion("erosion check completed")
    result.update({
        "checked": True,
        "atom_count": len(report["atoms"]),
        "eroded_atom_count": eroded,
        "atoms": atoms,
    })
    if returncode == 0 and report.get("status") == "pass":
        result["status"] = "passed"
        result["summary"] = "contract erosion check passed"
    elif hard_failure:
        result["status"] = "failed"
        result["summary"] = "contract erosion detected"
    elif inconclusive:
        result["status"] = "inconclusive"
        result["summary"] = "contract erosion check inconclusive"
    elif report.get("status") == "fail":
        result["status"] = "failed"
        result["summary"] = "contract erosion detected"
    else:
        result["status"] = "malformed"
        result["checked"] = False
        result["reason"] = "erosion report status was inconsistent with the command result"
    return result


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


def migration_output_function_stem(function_name: str) -> str:
    return function_name[:80]


def migration_output_target(output_dir: Path, source_path: str | Path, function_name: str, skeleton: str) -> Path:
    def occupied(candidate: Path) -> bool:
        backup = Path(str(candidate) + ".bak")
        return candidate.exists() or candidate.is_symlink() or backup.exists() or backup.is_symlink()

    key = migration_output_key(source_path, skeleton)
    candidate = output_dir / f"{migration_output_function_stem(function_name)}-{key}.mm"
    if not occupied(candidate):
        return candidate
    suffix = 1
    while True:
        candidate = output_dir / f"{migration_output_function_stem(function_name)}-{key}-{suffix}.mm"
        if not occupied(candidate):
            return candidate
        suffix += 1


def _canonical_mm_text(text: str) -> str:
    return text.rstrip() + "\n" if text.strip() else text


_ABSOLUTE_PATH_FRAGMENT = re.compile(r"(?<![\w])(?:/[^\s:;,()\[\]{}'\"]+)+")


def _redact_error_text(text: str) -> str:
    return redact_secrets(_ABSOLUTE_PATH_FRAGMENT.sub("<path>", str(text)))


def _healed_content(function_name: str, healed_files: list[str], skeleton: str, source_path: str, excluded_paths: set[str]) -> tuple[str, str | None, bool]:
    raw_base_names = {function_name, _safe_stem(function_name), _safe_identifier(function_name)}
    base_names = raw_base_names | {migration_output_function_stem(base) for base in raw_base_names}
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


def _python_definition_index(source: str) -> tuple[dict[str, tuple[int, int]], dict[str, list[tuple[int, int]]]] | None:
    """Map Python function definitions to their source spans.

    Returns ``(qualified, leaf_spans)`` where ``qualified`` maps dotted names
    (``Class.method``, ``function``) to every ``(lineno, end_lineno)`` span
    defining that name and ``leaf_spans`` maps each leaf name to every span
    defining it. A name can have several spans (for example the same class
    path defined in both branches of a conditional); such names are
    ambiguous and callers must not resolve or deduplicate them. Returns
    ``None`` when the source cannot be parsed, in which case no name can be
    resolved and callers must not deduplicate anything.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    qualified: dict[str, list[tuple[int, int]]] = {}
    leaf_spans: dict[str, list[tuple[int, int]]] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}.{child.name}" if prefix else child.name
                span = (child.lineno, child.end_lineno or child.lineno)
                qualified.setdefault(qualname, []).append(span)
                leaf_spans.setdefault(child.name, []).append(span)
                visit(child, qualname)
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}.{child.name}" if prefix else child.name)
            else:
                visit(child, prefix)

    visit(tree, "")
    return qualified, leaf_spans


def _resolve_python_definition_span(
    function_name: str,
    qualified: dict[str, list[tuple[int, int]]],
    leaf_spans: dict[str, list[tuple[int, int]]],
) -> tuple[int, int] | None:
    """Resolve a hint function name to one definition span, or ``None``.

    A qualified name resolves only when it exactly matches a class-path
    definition. An unqualified leaf resolves only when the file defines that
    leaf exactly once; multiple same-leaf definitions (for example a legit
    module-level function and a method sharing the name) stay unresolved so
    the caller never deduplicates on a guess.
    """
    if "." in function_name:
        spans = qualified.get(function_name, [])
    else:
        spans = leaf_spans.get(function_name, [])
    if len(spans) == 1:
        return spans[0]
    return None


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

    # Pass 1: attribute every hint to its source file exactly once, in the
    # same iteration/occurrence order the candidate loop below relies on, and
    # resolve Python hints to their function definition span. Hints that
    # cannot be resolved keep ``dedupe_key=None`` and are never merged.
    hint_records: list[dict[str, object]] = []
    definition_indexes: dict[str, tuple[dict[str, tuple[int, int]], dict[str, list[tuple[int, int]]]] | None] = {}
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
        dedupe_key: tuple[str, int, int, str] | None = None
        if str(hint_language).lower() == "python":
            if hint_source not in definition_indexes:
                definition_indexes[hint_source] = _python_definition_index(_read_source(hint_source))
            index_entry = definition_indexes[hint_source]
            if index_entry is not None:
                span = _resolve_python_definition_span(function_name, index_entry[0], index_entry[1])
                if span is not None:
                    # The canonical skeleton is part of the merge condition:
                    # hints resolving to the same span but carrying different
                    # skeletons are distinct review evidence and stay separate.
                    dedupe_key = (hint_source, span[0], span[1], str(hint.get("skeleton") or ""))
        hint_records.append(
            {
                "hint_index": hint_index,
                "hint": hint,
                "function_name": function_name,
                "file_result": file_result,
                "hint_source": hint_source,
                "hint_language": hint_language,
                "dedupe_key": dedupe_key,
            }
        )

    # Pass 2: group hints resolving to the same definition. The representative
    # is the first qualified-named hint in the group when one exists, else the
    # first hint; absorbed hints contribute their reason text to the
    # representative's selection reason so no review signal is lost. Position
    # keys are indexes into ``hint_records``.
    groups: dict[tuple[str, int, int, str], list[int]] = {}
    for position, record in enumerate(hint_records):
        key = record["dedupe_key"]
        if key is not None:
            groups.setdefault(key, []).append(position)
    skip_positions: set[int] = set()
    merged_reasons: dict[int, str] = {}
    for positions in groups.values():
        if len(positions) < 2:
            continue
        representative = positions[0]
        for position in positions:
            if "." in str(hint_records[position]["function_name"]):
                representative = position
                break
        reason_parts: list[str] = []
        for position in positions:
            record = hint_records[position]
            reason = str(record["hint"].get("reason") or "")
            if position == representative:
                reason_parts.insert(0, reason)
            else:
                alias = record["function_name"]
                reason_parts.append(f"duplicate hint for `{alias}` resolving to the same definition: {reason}")
                skip_positions.add(position)
        merged_reasons[representative] = "\n".join(part for part in reason_parts if part)

    for position, record in enumerate(hint_records):
        if position in skip_positions:
            continue
        hint_index = record["hint_index"]
        hint = record["hint"]
        function_name = record["function_name"]
        file_result = record["file_result"]
        hint_source = record["hint_source"]
        hint_language = record["hint_language"]
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
            "selection": {"selected": True, "reason": redact_secrets(merged_reasons.get(position, str(hint.get("reason") or "")))},
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
            "contract_erosion": _initial_contract_erosion("contract erosion check has not run"),
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
            raw_error_stems = {function_name, _safe_stem(function_name), _safe_identifier(function_name)}
            expected_error_stems = raw_error_stems | {migration_output_function_stem(base) for base in raw_error_stems}
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
                "requires_delta": _conjunct_delta(original_contract["requires"], contract["requires"]),
                "ensures_delta": _conjunct_delta(original_contract["ensures"], contract["ensures"]),
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
            candidate["contract_erosion"] = _contract_erosion_check(original_text, final_text, mumei_client=mumei_client)
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
