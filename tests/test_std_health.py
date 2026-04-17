"""Unit tests for ``agent.std_health`` — SI-5 Phase 3-A."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent import std_health


def _write_mm(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# compute_health_score
# ---------------------------------------------------------------------------


class TestComputeHealthScore:
    def test_zero_atoms_returns_zero(self) -> None:
        assert std_health.compute_health_score(0, 0, 0, 0) == 0.0

    def test_fully_verified_returns_one(self) -> None:
        assert std_health.compute_health_score(
            total_atoms=10,
            verified_atoms=10,
            trusted_atoms=0,
            todo_count=0,
        ) == 1.0

    def test_all_trusted_is_zero(self) -> None:
        # trusted == total means no net verification progress.
        assert std_health.compute_health_score(10, 10, 10, 0) == 0.0

    def test_partial_verification(self) -> None:
        # 6/10 atoms verified, none trusted, no TODOs → 0.6
        score = std_health.compute_health_score(10, 6, 0, 0)
        assert pytest.approx(score, abs=1e-9) == 0.6

    def test_todo_penalty_applied(self) -> None:
        base = std_health.compute_health_score(10, 10, 0, 0)
        with_todos = std_health.compute_health_score(10, 10, 0, 5)
        assert with_todos < base
        assert with_todos == pytest.approx(1.0 - 0.05, abs=1e-9)

    def test_todo_penalty_is_capped(self) -> None:
        # Even 10_000 TODOs cannot drive the score below 1.0 - MAX_PENALTY.
        score = std_health.compute_health_score(10, 10, 0, 10_000)
        assert score == pytest.approx(1.0 - std_health._MAX_TODO_PENALTY, abs=1e-9)

    def test_score_is_never_negative(self) -> None:
        score = std_health.compute_health_score(10, 0, 0, 10_000)
        assert score >= 0.0

    def test_score_is_never_greater_than_one(self) -> None:
        # Pathological inputs still clamp.
        score = std_health.compute_health_score(10, 100, 0, 0)
        assert score <= 1.0


# ---------------------------------------------------------------------------
# measure_health
# ---------------------------------------------------------------------------


class TestMeasureHealth:
    def test_missing_std_dir_returns_zero_metrics(
        self, tmp_path: Path, mock_mumei_client
    ) -> None:
        client = mock_mumei_client(verify_success=True)
        report = std_health.measure_health(client, tmp_path / "nope")
        assert report["total_files"] == 0
        assert report["health_score"] == 0.0
        assert "error" in report

    def test_empty_std_dir(self, tmp_path: Path, mock_mumei_client) -> None:
        std = tmp_path / "std"
        std.mkdir()
        client = mock_mumei_client(verify_success=True)
        report = std_health.measure_health(client, std)
        assert report["total_files"] == 0
        assert report["health_score"] == 0.0

    def test_all_files_verified(self, tmp_path: Path, mock_mumei_client) -> None:
        std = tmp_path / "std"
        _write_mm(
            std / "core.mm",
            "atom a(x: i64) ensures: true; body: x;\n"
            "atom b(y: i64) ensures: true; body: y;\n",
        )
        _write_mm(
            std / "iter.mm",
            "atom c(z: i64) ensures: true; body: z;\n",
        )
        client = mock_mumei_client(verify_success=True)
        report = std_health.measure_health(client, std)
        assert report["total_files"] == 2
        assert report["verified_files"] == 2
        assert report["failed_files"] == 0
        assert report["total_atoms"] == 3
        assert report["verified_atoms"] == 3
        assert report["trusted_atoms"] == 0
        assert report["health_score"] == 1.0

    def test_trusted_atoms_counted(
        self, tmp_path: Path, mock_mumei_client
    ) -> None:
        std = tmp_path / "std"
        _write_mm(
            std / "core.mm",
            "atom a(x: i64) ensures: true; body: x;\n"
            "trusted atom b(y: u64) ensures: true; body: {}\n",
        )
        client = mock_mumei_client(verify_success=True)
        report = std_health.measure_health(client, std)
        assert report["total_atoms"] == 2
        assert report["trusted_atoms"] == 1
        # verified_atoms counts all atoms when the file verifies, but the
        # score subtracts trusted.
        assert report["verified_atoms"] == 2
        assert report["health_score"] == pytest.approx(0.5, abs=1e-9)

    def test_failed_files_lower_score(
        self, tmp_path: Path, mock_mumei_client
    ) -> None:
        std = tmp_path / "std"
        _write_mm(std / "ok.mm", "atom ok(x: i64) ensures: true; body: x;\n")
        _write_mm(std / "fail.mm", "atom fail(x: i64) ensures: true; body: x;\n")
        # Mixed: first call ok, second call fail
        from unittest.mock import MagicMock

        client = MagicMock()
        client.verify.side_effect = [
            {"success": True, "report": {}, "stdout": "", "stderr": ""},
            {"success": False, "report": {}, "stdout": "", "stderr": "err"},
        ]
        report = std_health.measure_health(client, std)
        assert report["verified_files"] == 1
        assert report["failed_files"] == 1
        assert report["verified_atoms"] == 1
        assert report["health_score"] == pytest.approx(0.5, abs=1e-9)

    def test_todo_markers_counted(
        self, tmp_path: Path, mock_mumei_client
    ) -> None:
        std = tmp_path / "std"
        _write_mm(
            std / "core.mm",
            "// TODO: prove this\n// FIXME: broken\n"
            "atom a(x: i64) ensures: true; body: x;\n",
        )
        client = mock_mumei_client(verify_success=True)
        report = std_health.measure_health(client, std)
        assert report["todo_count"] == 2

    def test_details_include_per_file_metrics(
        self, tmp_path: Path, mock_mumei_client
    ) -> None:
        std = tmp_path / "std"
        _write_mm(std / "a.mm", "atom a(x: i64) ensures: true; body: x;\n")
        _write_mm(std / "b.mm", "trusted atom b(y: u64) ensures: true; body: {}\n")
        client = mock_mumei_client(verify_success=True)
        report = std_health.measure_health(client, std)
        detail_by_file = {d["file"]: d for d in report["details"]}
        assert detail_by_file["std/a.mm"]["atoms"] == 1
        assert detail_by_file["std/a.mm"]["trusted_atoms"] == 0
        assert detail_by_file["std/b.mm"]["trusted_atoms"] == 1


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_parses_required_args(self) -> None:
        import argparse

        parser = argparse.ArgumentParser()
        std_health.build_parser(parser)
        args = parser.parse_args(["--mumei-repo", "/tmp/m"])
        assert args.mumei_repo == "/tmp/m"
        assert args.format == "json"

    def test_format_table(self) -> None:
        import argparse

        parser = argparse.ArgumentParser()
        std_health.build_parser(parser)
        args = parser.parse_args(
            ["--mumei-repo", "/tmp/m", "--format", "table"]
        )
        assert args.format == "table"


# ---------------------------------------------------------------------------
# Table formatter
# ---------------------------------------------------------------------------


class TestFormatTable:
    def test_table_renders_headers(self) -> None:
        report = {
            "total_files": 1,
            "verified_files": 1,
            "failed_files": 0,
            "total_atoms": 1,
            "verified_atoms": 1,
            "trusted_atoms": 0,
            "health_score": 1.0,
            "todo_count": 0,
            "details": [
                {
                    "file": "std/ok.mm",
                    "verified": True,
                    "atoms": 1,
                    "trusted_atoms": 0,
                    "todos": 0,
                }
            ],
        }
        out = std_health._format_table(report)
        assert "Proof Health Report" in out
        assert "std/ok.mm" in out
        assert "1.000" in out
