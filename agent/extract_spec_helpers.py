"""Helper utilities for extract-spec orchestration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping
import sys


def _mumei_literal_for_type(type_name: str) -> str:
    normalized = type_name.strip().lower()
    if normalized in {"bool", "boolean"}:
        return "true"
    if normalized in {"str", "string"}:
        return '""'
    return "0"

def _clean_contract_clause(value: object, default: str = "true") -> str:
    text = str(value or default).strip()
    return text[:-1].strip() if text.endswith(";") else text

def _atom_params(atom: dict) -> str:
    params = atom.get("inputs", atom.get("params", []))
    if not isinstance(params, list):
        return ""
    rendered = []
    for param in params:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "").strip()
        type_name = str(param.get("type") or "i64").strip() or "i64"
        if name:
            rendered.append(f"{name}: {type_name}")
    return ", ".join(rendered)

def _spec_to_contradiction_check_module(spec: dict) -> str:
    atoms = spec.get("atoms")
    if not isinstance(atoms, list) or not atoms:
        raise ValueError("spec must contain a non-empty atoms list")

    blocks: list[str] = []
    for index, atom in enumerate(atoms):
        if not isinstance(atom, dict):
            raise ValueError(f"atoms[{index}] must be an object")
        name = str(atom.get("name") or f"extracted_atom_{index}").strip()
        if not name:
            raise ValueError(f"atoms[{index}].name must be non-empty")
        return_type = str(atom.get("return_type") or "i64").strip() or "i64"
        requires = _clean_contract_clause(atom.get("requires"))
        ensures = _clean_contract_clause(atom.get("ensures"))
        default_value = _mumei_literal_for_type(return_type)
        blocks.append(
            "\n".join(
                [
                    f"trusted atom {name}({_atom_params(atom)}) -> {return_type} {{",
                    f"    requires: {requires};",
                    f"    ensures: {ensures};",
                    "    body: {",
                    f"        {default_value}",
                    "    }",
                    "}",
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"

def _natural_language_contradiction_report(verify_result: dict) -> str:
    report = verify_result.get("report")
    if isinstance(report, dict):
        details = report.get("contradiction_details") or report.get("error")
        if details:
            return str(details)
        feedback = report.get("structured_feedback")
        if isinstance(feedback, dict):
            for key in ("message", "details", "suggested_fix"):
                if feedback.get(key):
                    return str(feedback[key])
        failed = report.get("failed")
        failed_count = failed if isinstance(failed, int) else 0
        if report.get("status") == "failed" or failed_count > 0:
            count = str(failed_count) if failed_count else "one or more"
            return (
                "SpecValidation failed for the synthesized specification: "
                f"Mumei reported {count} failed atom(s) while checking extracted contracts. "
                "At least one extracted requires/ensures clause is unsatisfiable or internally inconsistent."
            )
    stderr = str(verify_result.get("stderr") or "").strip()
    stdout = str(verify_result.get("stdout") or "").strip()
    combined = "\n".join(part for part in [stderr, stdout] if part)
    if "Spec contradiction" in combined or "SpecValidation failed" in combined:
        return combined
    return ""

def _code_extensions_for_language(
    extension_map: Mapping[str, str],
    language: str | None,
) -> list[str]:
    if language in {None, "unknown"}:
        return sorted(extension_map)
    return sorted(
        extension
        for extension, mapped_language in extension_map.items()
        if mapped_language == language
    )

_TEST_FILENAME_SUFFIXES = (
    "_test.go",
    ".test.ts",
    ".test.tsx",
    ".test.js",
    ".test.jsx",
    ".spec.ts",
    ".spec.tsx",
    ".spec.js",
    ".spec.jsx",
    "_test.py",
    ".t.sol",
)
_TEST_DIR_NAMES = frozenset({"tests", "__tests__", "testdata"})


def _is_test_file(path: Path, source_dir: Path) -> bool:
    """True when ``path`` is a language-idiomatic test file or lives in a test dir.

    Covers ``*_test.go``, ``*.test.ts`` / ``*.spec.ts`` (and js/tsx variants),
    ``test_*.py`` / ``*_test.py``, ``*.t.sol``, and any file under a ``tests`` /
    ``__tests__`` / ``testdata`` directory. Used to skip tests during directory
    audits by default (#286).
    """
    name = path.name.lower()
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if any(name.endswith(suffix) for suffix in _TEST_FILENAME_SUFFIXES):
        return True
    try:
        relative_parts = path.relative_to(source_dir).parts[:-1]
    except ValueError:
        relative_parts = path.parts[:-1]
    return any(part.lower() in _TEST_DIR_NAMES for part in relative_parts)


def _collect_code_files(
    source_dir: Path,
    extension_map: Mapping[str, str],
    language: str | None,
    *,
    include_tests: bool = True,
) -> list[Path]:
    extensions = set(_code_extensions_for_language(extension_map, language))
    if not extensions:
        return []
    return sorted(
        (
            path
            for path in source_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in extensions
            and (include_tests or not _is_test_file(path, source_dir))
        ),
        key=lambda path: path.relative_to(source_dir).as_posix(),
    )

def _read_text(args: argparse.Namespace) -> str:
    """Read requirement text from CLI arguments."""
    if args.text is not None:
        return args.text
    try:
        return Path(args.text_file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: Failed to read --text-file: {exc}", file=sys.stderr)
        sys.exit(1)

def _safe_task_filename(spec: dict) -> str:
    task_id = str(spec.get("task_id") or "extracted-spec")
    safe = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in task_id
    ).strip(".-")
    return f"{safe or 'extracted-spec'}.json"

def _write_forge_task_spec(spec: dict, tasks_dir: str) -> Path:
    path = Path(tasks_dir).resolve() / _safe_task_filename(spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
