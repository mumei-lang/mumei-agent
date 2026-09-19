"""Tests for ``scripts/measure_lean_ai_proof.py`` demonstrator hooks."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from scripts.measure_lean_ai_proof import (
    demote_atoms_to_unknown,
    measure_one,
)


def _cert(atoms: list[dict]) -> dict:
    return {
        "version": "1.1",
        "file": "cat/probe.mm",
        "atoms": atoms,
        "all_verified": all(
            a.get("z3_check_result") == "unsat" for a in atoms
        ),
    }


def test_demote_atoms_to_unknown_only_named_atoms() -> None:
    cert = _cert(
        [
            {"name": "sum_array", "status": "verified",
             "z3_check_result": "unsat", "z3_result_class": "unsat"},
            {"name": "other", "status": "verified",
             "z3_check_result": "unsat", "z3_result_class": "unsat"},
        ]
    )
    bridge_cert, forced = demote_atoms_to_unknown(cert, {"sum_array"})
    assert forced == ["sum_array"]
    demoted = bridge_cert["atoms"][0]
    assert demoted["z3_check_result"] == "unknown"
    assert demoted["z3_result_class"] == "unknown"
    assert demoted["status"] == "unknown"
    assert bridge_cert["atoms"][1]["z3_check_result"] == "unsat"
    assert bridge_cert["all_verified"] is False
    # The original certificate is untouched.
    assert cert["atoms"][0]["z3_check_result"] == "unsat"


def test_demote_atoms_to_unknown_no_match() -> None:
    cert = _cert([{"name": "a", "z3_check_result": "unsat"}])
    bridge_cert, forced = demote_atoms_to_unknown(cert, {"missing"})
    assert forced == []
    assert bridge_cert["all_verified"] is True


def _measure_config(tmp_path: Path) -> MagicMock:
    config = MagicMock()
    config.mumei_bin = "mumei"
    config.mumei_lean_repo = str(tmp_path / "mumei-lean")
    config.lean_ai_proof_max_attempts = 3
    config.lean_ai_proof_evidence_dir = ""
    return config


def test_measure_one_forces_atom_into_bridge(tmp_path: Path, monkeypatch) -> None:
    """A Z3-``unsat`` atom named via ``force_atoms`` reaches the bridge on a
    demoted copy; the written certificate merges the lean_verified record
    while ``forced_atoms`` documents the demotion."""
    from agent import lean_bridge
    from scripts import measure_lean_ai_proof as measure

    benchmarks = tmp_path / "benchmarks"
    src = benchmarks / "svcomp_style" / "loop_invariant.mm"
    src.parent.mkdir(parents=True)
    src.write_text("atom sum_array ...\n", encoding="utf-8")
    work_dir = tmp_path / "work"
    cert_dir = tmp_path / "certs"
    cert = _cert(
        [
            {"name": "sum_array", "status": "verified",
             "z3_check_result": "unsat", "z3_result_class": "unsat"},
        ]
    )

    def fake_z3(mumei_bin, source, out, timeout):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(cert), encoding="utf-8")
        return cert, {"returncode": 0, "output_tail": ""}

    seen: dict[str, str] = {}

    def fake_bridge(*, cert_path, lean_cert_out, **kwargs):
        payload = json.loads(Path(cert_path).read_text(encoding="utf-8"))
        seen["atom_status"] = payload["atoms"][0]["z3_check_result"]
        lean_cert = {
            "atoms": [{"name": "sum_array", "z3_check_result": "lean_verified"}]
        }
        lean_cert_out.write_text(json.dumps(lean_cert), encoding="utf-8")
        return {"success": True, "lean_cert": lean_cert}

    monkeypatch.setattr(measure, "_z3_proof_cert", fake_z3)
    monkeypatch.setattr(lean_bridge, "run_lean_bridge", fake_bridge)

    entry = measure_one(
        src,
        benchmarks_dir=benchmarks,
        work_dir=work_dir,
        cert_dir=cert_dir,
        config=_measure_config(tmp_path),
        generator=None,
        timeout=60.0,
        force_atoms=frozenset({"sum_array"}),
    )
    # The bridge saw the demoted copy.
    assert seen["atom_status"] == "unknown"
    assert entry["forced_atoms"] == ["sum_array"]
    assert entry["lean_verified_forced"] == 1
    upgraded = json.loads(
        (cert_dir / "svcomp_style" / "loop_invariant.proof.json").read_text()
    )
    assert upgraded["atoms"][0]["z3_check_result"] == "lean_verified"
    forced_input = json.loads(
        (
            work_dir / "svcomp_style" / "loop_invariant.forced.proof-cert.json"
        ).read_text()
    )
    assert forced_input["atoms"][0]["z3_check_result"] == "unknown"


def test_measure_one_forced_miss_restores_z3_verdict(
    tmp_path: Path, monkeypatch
) -> None:
    """A forced atom Lean fails to prove keeps its Z3 ``unsat`` verdict in
    the written certificate — the demotion only lives in the bridge input."""
    from agent import lean_bridge
    from scripts import measure_lean_ai_proof as measure

    benchmarks = tmp_path / "benchmarks"
    src = benchmarks / "svcomp_style" / "loop_invariant.mm"
    src.parent.mkdir(parents=True)
    src.write_text("atom sum_array ...\n", encoding="utf-8")
    cert_dir = tmp_path / "certs"
    cert = _cert(
        [
            {"name": "sum_array", "status": "verified",
             "z3_check_result": "unsat", "z3_result_class": "unsat"},
        ]
    )

    def fake_z3(mumei_bin, source, out, timeout):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(cert), encoding="utf-8")
        return cert, {"returncode": 0, "output_tail": ""}

    def fake_bridge(*, cert_path, lean_cert_out, **kwargs):
        lean_cert = {"atoms": []}  # nothing reached lean_verified
        lean_cert_out.write_text(json.dumps(lean_cert), encoding="utf-8")
        return {"success": True, "lean_cert": lean_cert}

    monkeypatch.setattr(measure, "_z3_proof_cert", fake_z3)
    monkeypatch.setattr(lean_bridge, "run_lean_bridge", fake_bridge)

    entry = measure_one(
        src,
        benchmarks_dir=benchmarks,
        work_dir=tmp_path / "work",
        cert_dir=cert_dir,
        config=_measure_config(tmp_path),
        generator=None,
        timeout=60.0,
        force_atoms=frozenset({"sum_array"}),
    )
    assert entry["forced_atoms"] == ["sum_array"]
    assert entry["lean_verified_forced"] == 0
    upgraded = json.loads(
        (cert_dir / "svcomp_style" / "loop_invariant.proof.json").read_text()
    )
    atom = upgraded["atoms"][0]
    assert atom["z3_check_result"] == "unsat"
    assert atom["status"] == "verified"


def test_measure_one_without_force_skips_bridge(tmp_path: Path, monkeypatch) -> None:
    """No unknown atoms and no --force-lean-atom -> the bridge never runs."""
    from agent import lean_bridge
    from scripts import measure_lean_ai_proof as measure

    benchmarks = tmp_path / "benchmarks"
    src = benchmarks / "cat" / "a.mm"
    src.parent.mkdir(parents=True)
    src.write_text("atom a ...\n", encoding="utf-8")
    cert = _cert(
        [{"name": "a", "status": "verified",
          "z3_check_result": "unsat", "z3_result_class": "unsat"}]
    )

    def fake_z3(mumei_bin, source, out, timeout):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(cert), encoding="utf-8")
        return cert, {"returncode": 0, "output_tail": ""}

    bridge_called = []
    monkeypatch.setattr(measure, "_z3_proof_cert", fake_z3)
    monkeypatch.setattr(
        lean_bridge, "run_lean_bridge",
        lambda **kwargs: bridge_called.append(kwargs) or {"success": True},
    )

    entry = measure_one(
        src,
        benchmarks_dir=benchmarks,
        work_dir=tmp_path / "work",
        cert_dir=tmp_path / "certs",
        config=_measure_config(tmp_path),
        generator=None,
        timeout=60.0,
    )
    assert bridge_called == []
    assert entry["forced_atoms"] == []
    assert entry["unknown_atoms"] == 0
