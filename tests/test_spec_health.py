"""Tests for spec-health checking strategy and MCP tool."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent import mcp_server
from agent.strategies.spec_health_strategy import (
    ContradictionInfo,
    OverConstrainedInfo,
    SpecHealthChecker,
    SpecHealthReport,
    VacuousInfo,
    build_parser,
    main,
)


def _payload(raw: str) -> dict:
    assert isinstance(raw, str)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# SpecHealthChecker — contradiction
# ---------------------------------------------------------------------------


class TestCheckContradiction:
    def test_detects_unsatisfiable_atom(self) -> None:
        atom_cert = {
            "name": "impossible_x",
            "spec_validation_result": {
                "is_satisfiable": False,
                "contradiction_details": "requires_unsat: x > 0 && x < 0",
            },
        }
        checker = SpecHealthChecker()
        result = checker.check_contradiction(atom_cert)

        assert len(result) == 1
        assert result[0].atom == "impossible_x"
        assert "requires_unsat" in result[0].details
        assert result[0].fix_suggestion

    def test_returns_none_for_satisfiable_atom(self) -> None:
        atom_cert = {
            "name": "safe_add",
            "spec_validation_result": {
                "is_satisfiable": True,
            },
        }
        checker = SpecHealthChecker()
        assert checker.check_contradiction(atom_cert) == []

    def test_returns_none_when_no_spec_validation(self) -> None:
        atom_cert = {"name": "no_svr"}
        checker = SpecHealthChecker()
        assert checker.check_contradiction(atom_cert) == []


# ---------------------------------------------------------------------------
# SpecHealthChecker — over-constrained
# ---------------------------------------------------------------------------


class TestCheckOverConstrained:
    def test_detects_unused_hypotheses(self) -> None:
        atom_cert = {
            "name": "over",
            "unused_hypotheses": {
                "unused_requires": ["x > 0"],
                "unused_invariants": ["x < 100"],
                "unused_effect_constraints": [],
            },
        }
        checker = SpecHealthChecker()
        result = checker.check_over_constrained(atom_cert)

        assert len(result) == 1
        assert result[0].atom == "over"
        assert result[0].unused_requires == ["x > 0"]
        assert result[0].unused_invariants == ["x < 100"]
        assert result[0].fix_suggestion

    def test_returns_none_when_no_unused(self) -> None:
        atom_cert = {
            "name": "clean",
            "unused_hypotheses": {
                "unused_requires": [],
                "unused_invariants": [],
                "unused_effect_constraints": [],
            },
        }
        checker = SpecHealthChecker()
        assert checker.check_over_constrained(atom_cert) == []


# ---------------------------------------------------------------------------
# SpecHealthChecker — vacuity
# ---------------------------------------------------------------------------


class TestCheckVacuity:
    def test_detects_vacuous_stderr(self) -> None:
        verify_result = {
            "stderr": (
                "Specification is vacuous: 1 out of 3 mutated implementations "
                "still passed verification for 'weak_spec'."
            ),
            "stdout": "",
        }
        checker = SpecHealthChecker()
        result = checker.check_vacuity(verify_result)

        assert len(result) == 1
        assert result[0].atom == "weak_spec"
        assert "vacuous" in result[0].message.lower()
        assert result[0].fix_suggestion

    def test_ignores_passed_vacuity(self) -> None:
        verify_result = {
            "stderr": "",
            "stdout": "  ✓ Vacuity check passed for 'safe_add': 1 mutations tested, none passed verification",
        }
        checker = SpecHealthChecker()
        assert checker.check_vacuity(verify_result) == []


# ---------------------------------------------------------------------------
# SpecHealthChecker — check_all
# ---------------------------------------------------------------------------


class TestCheckAll:
    def test_aggregates_all_checks(self) -> None:
        verify_result = {
            "success": False,
            "report": {},
            "stderr": "Specification is vacuous: ... for 'weak'.",
            "stdout": "",
        }
        proof_cert = {
            "atoms": [
                {
                    "name": "bad",
                    "spec_validation_result": {
                        "is_satisfiable": False,
                        "contradiction_details": "requires_unsat",
                    },
                    "unused_hypotheses": {
                        "unused_requires": ["x > 0"],
                        "unused_invariants": [],
                        "unused_effect_constraints": [],
                    },
                },
                {
                    "name": "good",
                    "spec_validation_result": {"is_satisfiable": True},
                    "unused_hypotheses": {
                        "unused_requires": [],
                        "unused_invariants": [],
                        "unused_effect_constraints": [],
                    },
                },
            ],
        }
        checker = SpecHealthChecker()
        report = checker.check_all(verify_result, proof_cert)

        assert len(report.contradictions) == 1
        assert report.contradictions[0].atom == "bad"
        assert len(report.over_constrained) == 1
        assert report.over_constrained[0].atom == "bad"
        assert len(report.vacuous) == 1
        assert report.vacuous[0].atom == "weak"
        assert report.fix_suggestions
        assert report.health_score < 1.0

    def test_fallback_when_no_atoms_and_failed(self) -> None:
        verify_result = {
            "success": False,
            "report": {"status": "failed", "failed": 2},
            "stderr": "",
            "stdout": "",
        }
        checker = SpecHealthChecker()
        report = checker.check_all(verify_result, proof_cert=None)

        assert len(report.contradictions) == 1
        assert "2 failed atom" in report.contradictions[0].details

    def test_perfect_health_score(self) -> None:
        verify_result = {
            "success": True,
            "report": {},
            "stderr": "",
            "stdout": "",
        }
        proof_cert = {
            "atoms": [
                {
                    "name": "ok",
                    "spec_validation_result": {"is_satisfiable": True},
                    "unused_hypotheses": {
                        "unused_requires": [],
                        "unused_invariants": [],
                        "unused_effect_constraints": [],
                    },
                }
            ],
        }
        checker = SpecHealthChecker()
        report = checker.check_all(verify_result, proof_cert)

        assert report.contradictions == []
        assert report.over_constrained == []
        assert report.vacuous == []
        assert report.health_score == 1.0


# ---------------------------------------------------------------------------
# SpecHealthReport — serialization
# ---------------------------------------------------------------------------


class TestSpecHealthReport:
    def test_to_dict_round_trip(self) -> None:
        report = SpecHealthReport(
            contradictions=[ContradictionInfo(atom="a", details="d")],
            over_constrained=[OverConstrainedInfo(atom="b", unused_requires=["r"])],
            vacuous=[VacuousInfo(atom="c", message="m")],
            health_score=0.5,
        )
        d = report.to_dict()
        assert d["health_score"] == 0.5
        assert d["contradictions"][0]["atom"] == "a"
        assert d["over_constrained"][0]["unused_requires"] == ["r"]
        assert d["vacuous"][0]["message"] == "m"
        assert "fix_suggestions" in d


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------


class TestCLI:
    def test_parser_accepts_input_and_output(self) -> None:
        args = build_parser().parse_args(["spec.mm", "--output", "report.json"])
        assert args.input == "spec.mm"
        assert args.output == "report.json"

    def test_main_writes_json_report(self, tmp_path: Path) -> None:
        source = tmp_path / "test.mm"
        output = tmp_path / "report.json"
        source.write_text(
            "atom ok(x: i64) -> i64\n    requires: x > 0;\n    ensures: result == x;\n    body: x;\n",
            encoding="utf-8",
        )
        # Mock MumeiClient.verify and proof cert
        mumei = MagicMock()
        mumei.verify.return_value = {
            "success": True,
            "report": {},
            "stdout": "",
            "stderr": "",
        }

        fake_cert = {
            "atoms": [
                {
                    "name": "ok",
                    "spec_validation_result": {"is_satisfiable": True},
                    "unused_hypotheses": {
                        "unused_requires": [],
                        "unused_invariants": [],
                        "unused_effect_constraints": [],
                    },
                }
            ],
        }
        cert_written = False

        def fake_verify(source_path, report_dir=None, extra_args=None):
            nonlocal cert_written
            if extra_args:
                for i, arg in enumerate(extra_args):
                    if arg == "--output" and i + 1 < len(extra_args):
                        Path(extra_args[i + 1]).write_text(
                            json.dumps(fake_cert), encoding="utf-8"
                        )
                        cert_written = True
            return {
                "success": True,
                "report": {},
                "stdout": "",
                "stderr": "",
            }

        mumei.verify.side_effect = fake_verify

        with patch(
            "agent.mumei_client.create_mumei_client",
            return_value=mumei,
        ):
            args = build_parser().parse_args(
                [str(source), "--output", str(output)]
            )
            report = main(args)

        assert report.health_score == 1.0
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["health_score"] == 1.0
        assert payload["contradictions"] == []


# ---------------------------------------------------------------------------
# MCP tool — check_spec_health
# ---------------------------------------------------------------------------


class TestMCPCheckSpecHealth:
    def test_contradiction_detected_via_mcp(self) -> None:
        source = (
            "atom impossible(x: i64) -> i64\n"
            "    requires: x > 0 && x < 0;\n"
            "    ensures: result >= 0;\n"
            "    body: x;\n"
        )
        # Simulate proof cert with unsatisfiable atom
        fake_cert = {
            "atoms": [
                {
                    "name": "impossible",
                    "spec_validation_result": {
                        "is_satisfiable": False,
                        "contradiction_details": "requires_unsat: x > 0 && x < 0",
                    },
                    "unused_hypotheses": {
                        "unused_requires": [],
                        "unused_invariants": [],
                        "unused_effect_constraints": [],
                    },
                }
            ],
        }

        def fake_verify(source_path, report_dir=None, extra_args=None):
            if extra_args:
                for i, arg in enumerate(extra_args):
                    if arg == "--output" and i + 1 < len(extra_args):
                        Path(extra_args[i + 1]).write_text(
                            json.dumps(fake_cert), encoding="utf-8"
                        )
            return {
                "success": False,
                "report": {"status": "failed", "failed": 1},
                "stdout": "",
                "stderr": "",
            }

        mumei = MagicMock()
        mumei.verify.side_effect = fake_verify

        with patch(
            "agent.mumei_client.create_mumei_client", return_value=mumei
        ):
            result = _payload(mcp_server.check_spec_health(source))

        assert result["status"] == "ok"
        assert len(result["contradictions"]) == 1
        assert result["contradictions"][0]["atom"] == "impossible"
        assert result["contradictions"][0]["fix_suggestion"]
        assert result["fix_suggestions"]
        assert result["health_score"] < 1.0

    def test_healthy_spec_returns_perfect_score(self) -> None:
        source = (
            "atom safe_add(a: i64, b: i64) -> i64\n"
            "    requires: a >= 0 && b >= 0;\n"
            "    ensures: result == a + b;\n"
            "    body: a + b;\n"
        )
        fake_cert = {
            "atoms": [
                {
                    "name": "safe_add",
                    "spec_validation_result": {"is_satisfiable": True},
                    "unused_hypotheses": {
                        "unused_requires": [],
                        "unused_invariants": [],
                        "unused_effect_constraints": [],
                    },
                }
            ],
        }

        def fake_verify(source_path, report_dir=None, extra_args=None):
            if extra_args:
                for i, arg in enumerate(extra_args):
                    if arg == "--output" and i + 1 < len(extra_args):
                        Path(extra_args[i + 1]).write_text(
                            json.dumps(fake_cert), encoding="utf-8"
                        )
            return {
                "success": True,
                "report": {},
                "stdout": "",
                "stderr": "",
            }

        mumei = MagicMock()
        mumei.verify.side_effect = fake_verify

        with patch(
            "agent.mumei_client.create_mumei_client", return_value=mumei
        ):
            result = _payload(mcp_server.check_spec_health(source))

        assert result["status"] == "ok"
        assert result["contradictions"] == []
        assert result["health_score"] == 1.0
