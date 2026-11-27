#!/usr/bin/env python3
"""Collect migration execution evidence into the audit action artifact."""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

SCHEMA = "mumei.migration-execution/v1"
STATES = ("ready_for_human_review", "blocked", "operational_error")


def _write_outputs(path: str, values: dict[str, object]) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _status_payload(status: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "ready_count": 0,
        "counts": {state: 0 for state in STATES},
        "review_required": False,
        "boundary": "Migration execution evidence is generated-.mm acceptance evidence only; it is not host-code semantic equivalence proof.",
    }
    payload.update(extra)
    return payload


def _finish(args: argparse.Namespace, payload: dict[str, object], *, error: str | None = None) -> int:
    target_dir = Path(args.state_dir) / "migration-execution"
    if error:
        payload["error"] = error
    if payload["status"] != "not_requested":
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "status.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    operational_error_count = counts.get("operational_error", 0)
    _write_outputs(
        args.github_output,
        {
            "migration_execution_status": payload["status"],
            "migration_execution_ready_count": payload["ready_count"],
            "migration_execution_operational_error_count": operational_error_count,
        },
    )
    candidate_operational_failure = payload["status"] == "emitted_by_audit_cli" and operational_error_count != 0
    if candidate_operational_failure:
        return 3
    return 2 if payload["status"] == "operational_error" else 0


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("migration execution artifact is not a JSON object")
    return value


def _validate(payload: dict[str, Any], migration_json: Path, workspace: Path) -> tuple[Path, dict[str, int], bool, str]:
    if payload.get("schema") != SCHEMA:
        raise ValueError("migration execution schema is missing or unsupported")
    required_top_level = {
        "schema",
        "generated_at",
        "source",
        "audit",
        "selection",
        "candidates",
        "operational_errors",
        "artifact_paths",
        "evidence_boundary",
        "summary",
    }
    if required_top_level - set(payload):
        raise ValueError("migration execution artifact is missing required top-level evidence keys")
    candidates = payload.get("candidates")
    summary = payload.get("summary")
    artifact_paths = payload.get("artifact_paths")
    boundary = payload.get("evidence_boundary")
    if not isinstance(candidates, list) or not isinstance(summary, dict) or not isinstance(artifact_paths, dict):
        raise ValueError("migration execution artifact is missing candidates, summary, or artifact paths")
    recorded_output = artifact_paths.get("migration_execution")
    if not isinstance(recorded_output, str):
        raise ValueError("migration execution output path is missing")
    recorded_path = Path(recorded_output)
    if not recorded_path.is_absolute():
        recorded_path = migration_json.parent / recorded_path
    if recorded_path.resolve(strict=False) != migration_json.resolve(strict=False):
        raise ValueError("migration execution output path does not match the requested artifact")
    generated_value = artifact_paths.get("generated_artifacts")
    if not isinstance(generated_value, str):
        raise ValueError("generated artifact directory path is missing")
    generated_dir = Path(generated_value)
    if not generated_dir.is_absolute():
        generated_dir = migration_json.parent / generated_dir
    if generated_dir.is_symlink() or not generated_dir.is_dir():
        raise ValueError("generated artifact directory is missing or is a symlink")
    generated_dir = generated_dir.resolve()
    if not generated_dir.is_relative_to(workspace):
        raise ValueError("generated artifact directory escapes the caller workspace")
    expected_base = migration_json.parent / f"{migration_json.stem}.migration-execution"
    if generated_dir != expected_base and not re.fullmatch(re.escape(expected_base.name) + r"-\d+", generated_dir.name):
        raise ValueError("generated artifact directory does not match the migration execution output")
    counts = {state: 0 for state in STATES}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("migration execution candidate is not an object")
        required_candidate = {
            "function_name",
            "source_provenance",
            "selection",
            "extracted_contract",
            "generated_mm",
            "heal",
            "verification",
            "unbound_audit_diagnostics",
            "contract_provenance",
            "evidence_blockers",
            "operational_errors",
            "review_required",
            "execution_state",
        }
        if required_candidate - set(candidate):
            raise ValueError("migration execution candidate is missing required evidence keys")
        state = candidate.get("execution_state")
        if state not in STATES:
            raise ValueError("migration execution candidate has an unknown execution state")
        counts[state] += 1
    for state in STATES:
        if summary.get(state) != counts[state]:
            raise ValueError("migration execution summary counts are inconsistent")
    if summary.get("candidate_count") != len(candidates):
        raise ValueError("migration execution candidate count is inconsistent")
    if not isinstance(summary.get("review_required"), bool):
        raise ValueError("migration execution review_required is missing")
    if not isinstance(boundary, list) or not boundary or not all(isinstance(item, str) for item in boundary):
        raise ValueError("migration execution evidence boundary is missing")
    return generated_dir, counts, bool(summary["review_required"]), boundary[0]


def _copy_generated(generated_dir: Path, target_dir: Path) -> int:
    copied = 0
    target_root = target_dir / "generated-artifacts"
    for source in sorted(generated_dir.rglob("*")):
        if source.is_symlink() or not source.is_file():
            continue
        relative = source.relative_to(generated_dir)
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requested", required=True, choices=("true", "false"))
    parser.add_argument("--cli-supported", required=True, choices=("true", "false"))
    parser.add_argument("--migration-json", default="")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--github-output", default="")
    parser.add_argument("--precheck-error", default="")
    args = parser.parse_args()

    if args.requested == "false":
        return _finish(args, _status_payload("not_requested"))
    if args.precheck_error:
        return _finish(args, _status_payload("operational_error"), error=args.precheck_error)
    if args.cli_supported == "false":
        return _finish(args, _status_payload("operational_error"), error="the current audit CLI does not support --migration-execution-output")
    migration_json = Path(args.migration_json)
    try:
        if migration_json.is_symlink() or not migration_json.is_file():
            raise ValueError("migration execution artifact was not produced as a regular file")
        payload = _load(migration_json)
        workspace = Path(args.workspace).resolve()
        generated_dir, counts, review_required, boundary = _validate(payload, migration_json, workspace)
        target_dir = Path(args.state_dir) / "migration-execution"
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(migration_json, target_dir / "migration_execution.json")
        copied = _copy_generated(generated_dir, target_dir)
        return _finish(
            args,
            _status_payload(
                "emitted_by_audit_cli",
                ready_count=counts["ready_for_human_review"],
                counts=counts,
                review_required=review_required,
                boundary=boundary,
                generated_artifacts_copied=copied,
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _finish(args, _status_payload("operational_error"), error=str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
