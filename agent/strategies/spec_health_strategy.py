"""Spec-health analysis strategy for AI-generated Mumei specifications.

Parses ``mumei verify --json`` proof-certificate output
(``spec_validation_result``, ``unused_hypotheses``) and
``--enable-vacuity-check`` diagnostics to classify atoms as
contradictory, over-constrained, or vacuous.

Typical usage::

    from agent.strategies.spec_health_strategy import SpecHealthChecker

    checker = SpecHealthChecker()
    report = checker.check_all(verify_result, proof_cert)
"""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ContradictionInfo:
    """An atom whose ``spec_validation_result.is_satisfiable`` is false."""

    atom: str
    details: str = ""


@dataclass
class OverConstrainedInfo:
    """An atom with many unused hypotheses (requires, invariants, effects)."""

    atom: str
    unused_requires: list[str] = field(default_factory=list)
    unused_invariants: list[str] = field(default_factory=list)
    unused_effect_constraints: list[str] = field(default_factory=list)


@dataclass
class VacuousInfo:
    """An atom flagged as vacuous by ``--enable-vacuity-check``."""

    atom: str
    message: str = ""


@dataclass
class SpecHealthReport:
    """Aggregated health report for a set of atoms."""

    contradictions: list[ContradictionInfo] = field(default_factory=list)
    over_constrained: list[OverConstrainedInfo] = field(default_factory=list)
    vacuous: list[VacuousInfo] = field(default_factory=list)
    health_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class SpecHealthChecker:
    """Analyse ``mumei verify`` output for spec quality issues."""

    # When an atom has more unused hypotheses than this threshold it is
    # flagged as over-constrained.
    over_constrained_threshold: int = 0

    def check_contradiction(self, atom_cert: dict[str, Any]) -> ContradictionInfo | None:
        """Return a :class:`ContradictionInfo` if the atom is unsatisfiable."""
        svr = atom_cert.get("spec_validation_result") or {}
        if svr.get("is_satisfiable") is False:
            return ContradictionInfo(
                atom=atom_cert.get("name", "unknown"),
                details=svr.get("contradiction_details", ""),
            )
        return None

    def check_over_constrained(self, atom_cert: dict[str, Any]) -> OverConstrainedInfo | None:
        """Return an :class:`OverConstrainedInfo` if unused hypotheses exceed the threshold."""
        uh = atom_cert.get("unused_hypotheses") or {}
        unused_req = uh.get("unused_requires") or []
        unused_inv = uh.get("unused_invariants") or []
        unused_eff = uh.get("unused_effect_constraints") or []
        total = len(unused_req) + len(unused_inv) + len(unused_eff)
        if total > self.over_constrained_threshold:
            return OverConstrainedInfo(
                atom=atom_cert.get("name", "unknown"),
                unused_requires=list(unused_req),
                unused_invariants=list(unused_inv),
                unused_effect_constraints=list(unused_eff),
            )
        return None

    def check_vacuity(self, verify_result: dict[str, Any]) -> list[VacuousInfo]:
        """Parse stderr / stdout for vacuity-check failure messages."""
        vacuous: list[VacuousInfo] = []
        for stream in ("stderr", "stdout"):
            text = verify_result.get(stream, "") or ""
            for line in text.splitlines():
                lower = line.lower()
                if "vacuous" in lower and "vacuity check passed" not in lower:
                    # Try to extract the atom name from
                    #   "Specification is vacuous: ..." or
                    #   "Vacuity check failed for 'name': ..."
                    atom = "unknown"
                    for marker in ("for '", "for \u2018"):
                        idx = line.find(marker)
                        if idx >= 0:
                            end = line.find("'", idx + len(marker))
                            if end < 0:
                                end = line.find("\u2019", idx + len(marker))
                            if end >= 0:
                                atom = line[idx + len(marker):end]
                            break
                    vacuous.append(VacuousInfo(atom=atom, message=line.strip()))
        return vacuous

    def check_all(
        self,
        verify_result: dict[str, Any],
        proof_cert: dict[str, Any] | None = None,
    ) -> SpecHealthReport:
        """Run all checks and produce a combined :class:`SpecHealthReport`.

        Parameters
        ----------
        verify_result:
            The dict returned by :meth:`MumeiClient.verify`.
        proof_cert:
            Optional proof certificate JSON (from ``--proof-cert``).
            When absent, falls back to ``verify_result["report"]``.
        """
        atoms = []
        if proof_cert and isinstance(proof_cert.get("atoms"), list):
            atoms = proof_cert["atoms"]
        else:
            report = verify_result.get("report") or {}
            if isinstance(report.get("atoms"), list):
                atoms = report["atoms"]

        contradictions: list[ContradictionInfo] = []
        over_constrained: list[OverConstrainedInfo] = []
        for atom_cert in atoms:
            c = self.check_contradiction(atom_cert)
            if c:
                contradictions.append(c)
            o = self.check_over_constrained(atom_cert)
            if o:
                over_constrained.append(o)

        vacuous = self.check_vacuity(verify_result)

        # If no atoms were found but verification failed, treat it as a
        # contradiction (the verifier catches the spec-sat failure before
        # producing a proof certificate).
        if not atoms and verify_result.get("success") is False:
            report = verify_result.get("report") or {}
            failed_count = report.get("failed", 0)
            if failed_count or report.get("status") == "failed":
                contradictions.append(ContradictionInfo(
                    atom="(spec-level)",
                    details=f"Verification failed with {failed_count} failed atom(s)",
                ))

        total = len(atoms) or 1
        issue_count = len(contradictions) + len(over_constrained) + len(vacuous)
        health_score = max(0.0, 1.0 - issue_count / total)

        return SpecHealthReport(
            contradictions=contradictions,
            over_constrained=over_constrained,
            vacuous=vacuous,
            health_score=round(health_score, 4),
        )


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def build_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    parser = parser or argparse.ArgumentParser(
        description="Check the health (contradiction / over-constraint / vacuity) of a Mumei spec.",
    )
    parser.add_argument("input", help="Path to a .mm source file to check.")
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Write the JSON health report to this file (default: stdout).",
    )
    parser.add_argument(
        "--mumei-repo",
        default="",
        help="Path to the mumei repo (used to locate the mumei binary).",
    )
    return parser


def main(args: argparse.Namespace | None = None) -> SpecHealthReport:
    """CLI entrypoint for ``python -m agent check-spec-health``."""
    if args is None:
        args = build_parser().parse_args()

    from agent.mumei_client import create_mumei_client

    mumei_bin = _resolve_mumei_bin(args.mumei_repo)
    client = create_mumei_client(mumei_bin)

    source_path = str(Path(args.input).expanduser().resolve())

    # Run verify with --json --enable-vacuity-check and --proof-cert to
    # get both the structured report and the per-atom certificate.
    with tempfile.TemporaryDirectory(prefix="mumei-spec-health-") as tmp:
        cert_path = str(Path(tmp) / "health.proof.json")
        verify_result = client.verify(
            source_path,
            report_dir=tmp,
            extra_args=["--enable-vacuity-check", "--proof-cert", "--output", cert_path],
        )
        cert_file = Path(cert_path)
        proof_cert = None
        if cert_file.exists():
            try:
                proof_cert = json.loads(cert_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

    checker = SpecHealthChecker()
    report = checker.check_all(verify_result, proof_cert)

    output = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
        logger.info("Health report written to %s", args.output)
    else:
        print(output)

    return report


def _resolve_mumei_bin(mumei_repo: str) -> str:
    """Best-effort resolution of the mumei binary path."""
    import os

    env_bin = os.environ.get("MUMEI_BIN", "")
    if env_bin:
        return env_bin

    if mumei_repo:
        for profile in ("release", "debug"):
            candidate = Path(mumei_repo) / "target" / profile / "mumei"
            if candidate.exists():
                return str(candidate)

    return "mumei"
