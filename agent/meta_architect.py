"""Meta-Architect: high-level architectural refactoring agent."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from openai import OpenAI

from agent.config import AgentConfig
from agent.mumei_client import MumeiClient

_logger = logging.getLogger(__name__)


@dataclass
class ContractConflict:
    caller_atom: str
    callee_atom: str
    caller_requires: str
    caller_ensures: str
    callee_requires: str
    callee_ensures: str
    violations: list[str]


@dataclass
class RefactoringProposal:
    proposal_id: str
    description: str
    refactoring_type: str
    target_atoms: list[str]
    changes: dict[str, Any]
    rationale: str


class MetaArchitect:
    """Analyze cross-atom oscillation and propose interface-level repairs."""

    def __init__(
        self,
        client: OpenAI,
        model: str,
        mumei_client: MumeiClient,
        config: AgentConfig,
    ):
        self.client = client
        self.model = model
        self.mumei_client = mumei_client
        self.config = config

    def analyze_architecture(
        self,
        source_files: list[Path],
        retry_history: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dependency_graph, cross_spec_reports = self._collect_cross_spec_reports(source_files)
        circular_dependencies = self._detect_cycles(dependency_graph)
        contract_conflicts = self._analyze_contract_conflicts_from_reports(
            cross_spec_reports,
            source_files,
        )
        refactoring_proposals = self._generate_refactoring_proposals(
            dependency_graph,
            circular_dependencies,
            contract_conflicts,
            retry_history,
        )

        return {
            "circular_dependencies": circular_dependencies,
            "contract_conflicts": [asdict(conflict) for conflict in contract_conflicts],
            "dependency_graph": dependency_graph,
            "refactoring_proposals": [
                asdict(proposal) for proposal in refactoring_proposals
            ],
        }

    def _collect_cross_spec_reports(
        self,
        source_files: list[Path],
    ) -> tuple[dict[str, dict[str, list[str]]], list[dict[str, Any]]]:
        graph: dict[str, dict[str, list[str]]] = {}
        reports: list[dict[str, Any]] = []
        for source_file in source_files:
            with TemporaryDirectory(prefix="meta_architect_") as report_dir:
                result = self._verify_cross_spec(source_file, report_dir)
                if not result.get("success"):
                    _logger.debug(
                        "cross-spec verification failed for %s: %s",
                        source_file,
                        result.get("stderr") or result.get("stdout"),
                    )
                    continue
                cross_spec_path = Path(report_dir) / "cross_spec.json"
                if not cross_spec_path.exists():
                    continue
                try:
                    cross_spec = json.loads(cross_spec_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    _logger.warning("invalid cross-spec JSON in %s", cross_spec_path)
                    continue
                reports.append(cross_spec)
                for node in cross_spec.get("dependency_graph", []):
                    atom_name = str(node.get("atom_name") or "")
                    if not atom_name:
                        continue
                    graph[atom_name] = {
                        "dependencies": _as_string_list(node.get("dependencies")),
                        "dependents": _as_string_list(node.get("dependents")),
                    }
        return graph, reports

    def _verify_cross_spec(self, source_file: Path, report_dir: str) -> dict[str, Any]:
        try:
            return self.mumei_client.verify(
                str(source_file),
                report_dir=report_dir,
                extra_args=["--cross-spec-verify"],
            )
        except TypeError:
            try:
                return self.mumei_client.verify(
                    str(source_file),
                    report_dir=report_dir,
                )
            except TypeError:
                return self.mumei_client.verify(str(source_file))

    def _build_dependency_graph(
        self,
        source_files: list[Path],
    ) -> dict[str, dict[str, list[str]]]:
        graph, _reports = self._collect_cross_spec_reports(source_files)
        return graph

    def _detect_cycles(
        self,
        dependency_graph: dict[str, dict[str, list[str]]],
    ) -> list[list[str]]:
        cycles: list[list[str]] = []
        cycle_keys: set[tuple[str, ...]] = set()
        visited: set[str] = set()
        rec_stack: set[str] = set()
        path: list[str] = []

        def dfs(node: str) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in sorted(dependency_graph.get(node, {}).get("dependencies", [])):
                if neighbor not in dependency_graph:
                    continue
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    key = _canonical_cycle_key(cycle)
                    if key not in cycle_keys:
                        cycle_keys.add(key)
                        cycles.append(cycle)

            path.pop()
            rec_stack.remove(node)

        for node in sorted(dependency_graph):
            if node not in visited:
                dfs(node)

        cycles.sort()
        return cycles

    def _analyze_contract_conflicts(self, source_files: list[Path]) -> list[ContractConflict]:
        _graph, reports = self._collect_cross_spec_reports(source_files)
        return self._analyze_contract_conflicts_from_reports(reports, source_files)

    def _analyze_contract_conflicts_from_reports(
        self,
        reports: list[dict[str, Any]],
        source_files: list[Path],
    ) -> list[ContractConflict]:
        contracts = _collect_atom_contracts(source_files)
        conflicts: list[ContractConflict] = []
        for cross_spec in reports:
            raw_conflicts = cross_spec.get("contract_conflicts", [])
            if not raw_conflicts:
                raw_conflicts = [
                    result
                    for result in cross_spec.get("contract_consistency", [])
                    if not result.get("is_consistent", True)
                ]
            for conflict in raw_conflicts:
                caller = str(conflict.get("caller_atom") or "")
                callee = str(conflict.get("callee_atom") or "")
                if not caller or not callee:
                    continue
                caller_contract = contracts.get(caller, {})
                callee_contract = contracts.get(callee, {})
                conflicts.append(
                    ContractConflict(
                        caller_atom=caller,
                        callee_atom=callee,
                        caller_requires=str(caller_contract.get("requires", "true")),
                        caller_ensures=str(caller_contract.get("ensures", "true")),
                        callee_requires=str(callee_contract.get("requires", "true")),
                        callee_ensures=str(callee_contract.get("ensures", "true")),
                        violations=_as_string_list(conflict.get("violations")),
                    )
                )
        return conflicts

    def _generate_refactoring_proposals(
        self,
        dependency_graph: dict[str, dict[str, list[str]]],
        circular_dependencies: list[list[str]],
        contract_conflicts: list[ContractConflict],
        retry_history: dict[str, Any] | None = None,
    ) -> list[RefactoringProposal]:
        proposals: list[RefactoringProposal] = []

        for conflict in contract_conflicts:
            violation_text = " ".join(conflict.violations).lower()
            if "requires" in violation_text or "caller contract provides" in violation_text:
                proposals.append(
                    RefactoringProposal(
                        proposal_id=f"relax_{conflict.callee_atom}",
                        description=(
                            f"Relax {conflict.callee_atom} requires to match "
                            f"{conflict.caller_atom} guarantees"
                        ),
                        refactoring_type="relax_requires",
                        target_atoms=[conflict.callee_atom],
                        changes={
                            "atom": conflict.callee_atom,
                            "requires": conflict.caller_ensures or "true",
                        },
                        rationale="Resolves caller/callee contract mismatch by raising the interface abstraction.",
                    )
                )

        for index, cycle in enumerate(circular_dependencies, start=1):
            proposals.append(
                RefactoringProposal(
                    proposal_id=f"split_cycle_{index}",
                    description=f"Split atoms in cycle {cycle} to break circular dependency",
                    refactoring_type="split_atom",
                    target_atoms=cycle,
                    changes={"action": "extract_interface"},
                    rationale="Breaks circular dependency by introducing an abstraction layer.",
                )
            )

        if retry_history and not proposals:
            attempts = retry_history.get("attempts", [])
            if isinstance(attempts, list) and len(attempts) >= 5 and dependency_graph:
                central_atom = max(
                    dependency_graph,
                    key=lambda atom: len(dependency_graph[atom].get("dependents", [])),
                )
                proposals.append(
                    RefactoringProposal(
                        proposal_id=f"abstract_{central_atom}",
                        description=f"Extract interface boundary around {central_atom}",
                        refactoring_type="split_atom",
                        target_atoms=[central_atom],
                        changes={"action": "extract_interface"},
                        rationale="Budget exhaustion without a local fix suggests raising interface abstraction.",
                    )
                )

        return proposals


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _canonical_cycle_key(cycle: list[str]) -> tuple[str, ...]:
    if len(cycle) > 1 and cycle[0] == cycle[-1]:
        cycle = cycle[:-1]
    if not cycle:
        return tuple()
    rotations = [tuple(cycle[index:] + cycle[:index]) for index in range(len(cycle))]
    return min(rotations)


def _collect_atom_contracts(source_files: list[Path]) -> dict[str, dict[str, str]]:
    contracts: dict[str, dict[str, str]] = {}
    for source_file in source_files:
        try:
            source = source_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for atom_name, atom_body in _iter_atom_blocks(source):
            contracts[atom_name] = {
                "requires": _extract_contract_clause(atom_body, "requires") or "true",
                "ensures": _extract_contract_clause(atom_body, "ensures") or "true",
            }
    return contracts


def _iter_atom_blocks(source: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"\batom\s+([A-Za-z_][A-Za-z0-9_:]*)", source))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        blocks.append((match.group(1), source[match.start():end]))
    return blocks


def _extract_contract_clause(atom_body: str, clause: str) -> str | None:
    pattern = rf"{clause}\s*:?\s*(.*?);"
    match = re.search(pattern, atom_body, flags=re.DOTALL)
    if not match:
        return None
    return " ".join(match.group(1).split())
