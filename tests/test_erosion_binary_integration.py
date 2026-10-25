from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest


def _run_erosion(
    binary: str, candidate: Path, baseline: Path
) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [
            *shlex.split(binary),
            "erosion",
            str(candidate),
            "--baseline",
            str(baseline),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result, json.loads(result.stdout)


def test_real_mumei_erosion_binary_detects_weakened_contract_and_body_only_change(
    tmp_path: Path,
) -> None:
    binary = os.environ.get("MUMEI_EROSION_BIN")
    if not binary:
        pytest.skip("MUMEI_EROSION_BIN is not set")

    baseline = tmp_path / "baseline.mm"
    candidate = tmp_path / "candidate.mm"
    baseline.write_text(
        "trusted atom clamp(x: i64, hi: i64) -> i64 "
        "requires: x >= 0; "
        "ensures: result >= 0 && result <= hi; "
        "body: 0;",
        encoding="utf-8",
    )
    candidate.write_text(
        "atom clamp(x: i64, hi: i64) -> i64 "
        "requires: x >= 0; "
        "ensures: result >= 0; "
        "body: 0;",
        encoding="utf-8",
    )
    dropped, dropped_report = _run_erosion(binary, candidate, baseline)
    assert dropped.returncode == 1
    assert dropped_report["atoms"][0]["status"] == "post_weakened"

    candidate.write_text(
        "atom clamp(x: i64, hi: i64) -> i64 "
        "requires: x >= 0; "
        "ensures: result >= 0 && result <= hi; "
        "body: 1;",
        encoding="utf-8",
    )
    body_only, body_report = _run_erosion(binary, candidate, baseline)
    assert body_only.returncode == 0
    assert body_report["status"] == "pass"
    assert body_report["atoms"][0]["status"] == "preserved"
