"""vStd roadmap gap analysis for forge automation.

This module turns the offline std gap rules into a CI-friendly roadmap report:
it classifies missing std modules, checks whether each roadmap item already has
a forge task spec, and emits proposal records that ``agent.propose`` can convert
into ``forge_tasks/vstd_*.json`` files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent.gap_rules import _STD_GAP_RULES, analyze_gaps_local


def task_filename_for_target(target: str) -> str:
    """Return the canonical ``forge_tasks`` filename for a std target."""
    slug = target
    if slug.startswith("std/"):
        slug = slug[len("std/") :]
    if slug.endswith(".mm"):
        slug = slug[: -len(".mm")]
    return f"vstd_{slug.replace('/', '_')}.json"


def classify_priority(
    rule: dict[str, Any],
    *,
    existing_paths: set[str],
    forge_task_exists: bool,
) -> str:
    """Classify roadmap priority as low / medium / high."""
    target = str(rule.get("target", ""))
    if target in existing_paths and forge_task_exists:
        return "low"
    depends_on = [dep for dep in rule.get("depends_on", []) if isinstance(dep, str)]
    unmet_deps = [dep for dep in depends_on if dep not in existing_paths]
    difficulty = str(rule.get("difficulty", "medium")).lower()
    if not forge_task_exists and not unmet_deps:
        return "high"
    if difficulty == "high" or unmet_deps:
        return "medium"
    return "low"


def analyze_vstd_roadmap(
    *,
    std_dir: Path,
    forge_tasks_dir: Path,
) -> dict[str, Any]:
    """Build a vStd roadmap report with forge task coverage metrics."""
    local_gaps = analyze_gaps_local(std_dir)
    dependency_graph = local_gaps.get("dependency_graph") or {}
    existing_paths = set(dependency_graph.keys())

    roadmap_items: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    taskized = 0
    existing_modules = 0

    priority_rank = {"high": 1, "medium": 2, "low": 3}
    for rule in _STD_GAP_RULES:
        target = str(rule["target"])
        task_filename = task_filename_for_target(target)
        task_path = forge_tasks_dir / task_filename
        forge_task_exists = task_path.exists()
        std_module_exists = target in existing_paths
        if forge_task_exists:
            taskized += 1
        if std_module_exists:
            existing_modules += 1

        depends_on = [dep for dep in rule.get("depends_on", []) if isinstance(dep, str)]
        unmet_deps = [dep for dep in depends_on if dep not in existing_paths]
        priority = classify_priority(
            rule,
            existing_paths=existing_paths,
            forge_task_exists=forge_task_exists,
        )
        status = (
            "implemented"
            if std_module_exists
            else "taskized"
            if forge_task_exists
            else "needs_forge_task"
        )

        item = {
            "name": target,
            "reason": rule.get("reason", ""),
            "depends_on": depends_on,
            "difficulty": rule.get("difficulty", "medium"),
            "priority": priority,
            "unmet_depends_on": unmet_deps,
            "std_module_exists": std_module_exists,
            "forge_task_exists": forge_task_exists,
            "forge_task_path": str(task_path),
            "roadmap_status": status,
        }
        roadmap_items.append(item)
        if not forge_task_exists:
            proposals.append(
                {
                    "name": target,
                    "reason": rule.get("reason", ""),
                    "depends_on": depends_on,
                    "difficulty": rule.get("difficulty", "medium"),
                    "priority": priority_rank.get(priority, 100),
                    "priority_band": priority,
                    "roadmap_status": status,
                }
            )

    total = len(roadmap_items)
    conversion_rate = taskized / total if total else 1.0
    verification_target_rate = existing_modules / total if total else 1.0
    return {
        "dependency_graph": dependency_graph,
        "trusted_atoms": local_gaps.get("trusted_atoms", []),
        "todo_comments": local_gaps.get("todo_comments", []),
        "proposals": proposals,
        "roadmap_items": roadmap_items,
        "metrics": {
            "roadmap_items": total,
            "forge_task_specs": taskized,
            "forge_task_conversion_rate": conversion_rate,
            "existing_std_modules": existing_modules,
            "verification_target_rate": verification_target_rate,
            "missing_forge_tasks": len(proposals),
        },
    }


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(
            prog="python -m agent analyze-std-gaps",
            description="Analyze vStd roadmap gaps and forge task coverage.",
        )
    parser.add_argument(
        "--std-dir",
        default="../mumei/std",
        help="Path to the mumei std directory.",
    )
    parser.add_argument(
        "--forge-tasks-dir",
        default="forge_tasks",
        help="Path to the forge_tasks directory.",
    )
    parser.add_argument(
        "--output-json",
        help="Optional path to write the roadmap gap report as JSON.",
    )
    return parser


def main(args: argparse.Namespace | None = None) -> None:
    if args is None:
        parser = build_parser()
        args = parser.parse_args()
    report = analyze_vstd_roadmap(
        std_dir=Path(args.std_dir),
        forge_tasks_dir=Path(args.forge_tasks_dir),
    )
    output = json.dumps(report, indent=2, ensure_ascii=False)
    if getattr(args, "output_json", None):
        path = Path(args.output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
