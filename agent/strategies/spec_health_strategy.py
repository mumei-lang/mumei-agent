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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class SpecHealthChecker:
    """Analyse ``mumei verify`` output for spec quality issues."""

    def __init__(self, over_constrained_threshold: int = 0) -> None:
        self.over_constrained_threshold = over_constrained_threshold

    def check_contradiction(self, spec_json: dict[str, object]) -> list[ContradictionInfo]:
        """Return atoms whose ``spec_validation_result`` is unsatisfiable."""
        contradictions: list[ContradictionInfo] = []
        for atom_cert in _collect_atoms(spec_json):
            contradiction = self._check_atom_contradiction(atom_cert)
            if contradiction:
                contradictions.append(contradiction)
        return contradictions

    def _check_atom_contradiction(
        self,
        atom_cert: dict[str, object],
    ) -> ContradictionInfo | None:
        svr = _as_dict(atom_cert.get("spec_validation_result"))
        if svr.get("is_satisfiable") is False:
            return ContradictionInfo(
                atom=_string_value(atom_cert.get("name"), "unknown"),
                details=_string_value(svr.get("contradiction_details")),
            )
        return None

    def check_over_constrained(self, spec_json: dict[str, object]) -> list[OverConstrainedInfo]:
        """Return atoms whose unused hypotheses exceed the threshold."""
        over_constrained: list[OverConstrainedInfo] = []
        for atom_cert in _collect_atoms(spec_json):
            issue = self._check_atom_over_constrained(atom_cert)
            if issue:
                over_constrained.append(issue)
        return over_constrained

    def _check_atom_over_constrained(
        self,
        atom_cert: dict[str, object],
    ) -> OverConstrainedInfo | None:
        uh = _as_dict(atom_cert.get("unused_hypotheses"))
        unused_req = _string_list(uh.get("unused_requires"))
        unused_inv = _string_list(uh.get("unused_invariants"))
        unused_eff = _string_list(uh.get("unused_effect_constraints"))
        total = len(unused_req) + len(unused_inv) + len(unused_eff)
        if total > self.over_constrained_threshold:
            return OverConstrainedInfo(
                atom=_string_value(atom_cert.get("name"), "unknown"),
                unused_requires=unused_req,
                unused_invariants=unused_inv,
                unused_effect_constraints=unused_eff,
            )
        return None

    def check_vacuity(self, verify_result: dict[str, object]) -> list[VacuousInfo]:
        """Parse stderr / stdout for vacuity-check failure messages."""
        vacuous: list[VacuousInfo] = []
        fallback_atom = _string_value(_as_dict(verify_result.get("report")).get("atom"), "unknown")
        for text in _vacuity_texts(verify_result):
            for line in text.splitlines():
                lower = line.lower()
                if "vacuous" in lower and "vacuity check passed" not in lower:
                    atom = _extract_atom_from_vacuity_line(line, fallback_atom)
                    vacuous.append(VacuousInfo(atom=atom, message=line.strip()))
        return vacuous

    def check_all(
        self,
        verify_result: dict[str, object],
        proof_cert: dict[str, object] | None = None,
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
        spec_json = proof_cert or _as_dict(verify_result.get("report"))
        atoms = _collect_atoms(spec_json)

        contradictions = self.check_contradiction(spec_json)
        over_constrained = self.check_over_constrained(spec_json)

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


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return {}


def _string_value(value: object, default: str = "") -> str:
    if isinstance(value, str):
        return value
    return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _collect_atoms(spec_json: dict[str, object]) -> list[dict[str, object]]:
    atoms = spec_json.get("atoms")
    if isinstance(atoms, list):
        return [_as_dict(atom) for atom in atoms if isinstance(atom, dict)]

    report = _as_dict(spec_json.get("report"))
    report_atoms = report.get("atoms")
    if isinstance(report_atoms, list):
        return [_as_dict(atom) for atom in report_atoms if isinstance(atom, dict)]

    if "spec_validation_result" in spec_json or "unused_hypotheses" in spec_json:
        return [spec_json]
    return []


def _vacuity_texts(verify_result: dict[str, object]) -> list[str]:
    texts: list[str] = []
    for key in ("stderr", "stdout"):
        value = verify_result.get(key)
        if isinstance(value, str) and value:
            texts.append(value)

    report = _as_dict(verify_result.get("report"))
    for key in ("reason", "message", "error"):
        value = report.get(key)
        if isinstance(value, str) and value:
            texts.append(value)

    diagnostics = report.get("diagnostics")
    if isinstance(diagnostics, list):
        texts.extend(item for item in diagnostics if isinstance(item, str))
    return texts


def _extract_atom_from_vacuity_line(line: str, fallback: str) -> str:
    for marker, quote in (("for '", "'"), ("for \u2018", "\u2019")):
        idx = line.find(marker)
        if idx >= 0:
            end = line.find(quote, idx + len(marker))
            if end >= 0:
                return line[idx + len(marker):end]
    return fallback


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
