"""Phase 2-C — Self-Healing + Forge integration loop (proliferate).

Autonomous proliferation loop that chains:
  analyze_std_gaps → propose (spec generation) → generate_code (forge) →
  blast-radius check (existing std impact) → self-healing repair → publish PR

Usage::

    python -m agent proliferate --mumei-repo /path/to/mumei [--max-proposals 3] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from agent.config import AgentConfig
from agent.mumei_client import MumeiClient
from agent.propose import build_spec_from_proposal
from agent.publish import publish
from agent.strategies.generate_strategy import generate_code

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gap Analysis (local filesystem, no MCP required)
# ---------------------------------------------------------------------------

# Regex patterns ported from mumei's mcp_server.py helper functions
_IMPORT_RE = re.compile(r'^\s*import\s+"([^"]+)"\s*(?:as\s+\w+\s*)?;')
_TRUSTED_ATOM_RE = re.compile(r"^\s*trusted\s+atom\s+(\w+)")
_TODO_MARKER_RE = re.compile(
    r"//.*?\b(TODO|FIXME|XXX|HACK|Phase\s+[A-Z0-9]+)\b[^\n]*",
    re.IGNORECASE,
)
_ATOM_RE = re.compile(r"^\s*(?:trusted\s+|async\s+)?atom\s+(\w+)")

# Hard-coded gap rules (same as mumei's mcp_server.py _STD_GAP_RULES).
_STD_GAP_RULES: list[dict[str, Any]] = [
    {
        "target": "std/iter.mm",
        "reason": (
            "Collection traversal common interface. "
            "std/list.mm / std/alloc.mm containers lack iterators."
        ),
        "depends_on": ["std/prelude.mm"],
        "difficulty": "medium",
        "trigger": {
            "has_container_without_iter": [
                "std/container",
                "std/list.mm",
                "std/alloc.mm",
            ],
            "missing": "std/iter.mm",
        },
    },
    {
        "target": "std/core.mm",
        "reason": (
            "Type conversion safety proofs are scattered. "
            "Consolidate Size/Index/NonZero axioms and checked_add/sub/mul."
        ),
        "depends_on": ["std/prelude.mm"],
        "difficulty": "low",
        "trigger": {"missing": "std/core.mm"},
    },
    {
        "target": "std/trait/iterable.mm",
        "reason": (
            "Common interface for Vector/List/BoundedArray. "
            "Connect Sequential trait with iterator."
        ),
        "depends_on": ["std/prelude.mm", "std/alloc.mm"],
        "difficulty": "medium",
        "trigger": {
            "missing": "std/trait/iterable.mm",
            "requires_present": ["std/alloc.mm"],
        },
    },
    {
        "target": "std/hash.mm",
        "reason": (
            "prelude.mm has Eq/Ord but Hash law is incomplete. "
            "Provide Hashable trait implementation and collision resistance law."
        ),
        "depends_on": ["std/prelude.mm"],
        "difficulty": "medium",
        "trigger": {"missing": "std/hash.mm"},
    },
]


def _scan_std_imports(std_dir: Path) -> dict[str, list[str]]:
    """Build a dependency graph of .mm files under *std_dir*.

    Returns a dict mapping ``std/X.mm`` relative paths to their sorted
    list of import targets.
    """
    if not std_dir.exists():
        return {}

    available: dict[str, str] = {}
    for mm_file in std_dir.rglob("*.mm"):
        rel = str(mm_file.relative_to(std_dir.parent)).replace("\\", "/")
        import_path = rel[: -len(".mm")]
        available[import_path] = rel

    dependency_graph: dict[str, list[str]] = {}
    for mm_file in sorted(std_dir.rglob("*.mm")):
        rel = str(mm_file.relative_to(std_dir.parent)).replace("\\", "/")
        try:
            text = mm_file.read_text(encoding="utf-8")
        except OSError:
            dependency_graph[rel] = []
            continue
        deps: list[str] = []
        for line in text.splitlines():
            m = _IMPORT_RE.match(line)
            if not m:
                continue
            target = m.group(1).strip()
            resolved = available.get(target)
            if resolved and resolved != rel and resolved not in deps:
                deps.append(resolved)
        dependency_graph[rel] = sorted(deps)
    return dependency_graph


def _collect_trusted_atoms(std_dir: Path) -> list[dict[str, Any]]:
    """Return list of trusted atom entries found in *std_dir*."""
    results: list[dict[str, Any]] = []
    for mm_file in sorted(std_dir.rglob("*.mm")):
        rel = str(mm_file.relative_to(std_dir.parent)).replace("\\", "/")
        try:
            lines = mm_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines):
            m = _TRUSTED_ATOM_RE.match(line)
            if not m:
                continue
            atom_name = m.group(1)
            reason = ""
            look = idx - 1
            while look >= 0 and lines[look].strip().startswith("//"):
                reason = lines[look].strip().lstrip("/ ").strip()
                look -= 1
            if not reason:
                end = min(idx + 10, len(lines))
                body_text = " ".join(l.strip() for l in lines[idx + 1 : end])
                if re.search(r"body\s*:\s*\{\s*\}", body_text):
                    reason = "body is stub"
                else:
                    reason = "trusted (proof hole)"
            results.append(
                {"file": rel, "atom": atom_name, "line": idx + 1, "reason": reason}
            )
    return results


def _collect_todo_comments(std_dir: Path) -> list[dict[str, Any]]:
    """Return list of TODO/FIXME/XXX/HACK comments in *std_dir*."""
    results: list[dict[str, Any]] = []
    for mm_file in sorted(std_dir.rglob("*.mm")):
        rel = str(mm_file.relative_to(std_dir.parent)).replace("\\", "/")
        try:
            lines = mm_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines):
            m = _TODO_MARKER_RE.search(line)
            if not m:
                continue
            results.append(
                {"file": rel, "line": idx + 1, "text": line.strip().lstrip("/ ").strip()}
            )
    return results


def _evaluate_rule(
    rule: dict[str, Any],
    existing_paths: set[str],
    std_dir: Path,
) -> bool:
    """Return True if the rule's trigger conditions apply."""
    trigger = rule.get("trigger", {})
    missing = trigger.get("missing")
    if missing and missing in existing_paths:
        return False
    for required in trigger.get("requires_present", []):
        if required not in existing_paths:
            return False
    container_check = trigger.get("has_container_without_iter")
    if container_check:
        has_container = any(
            (std_dir.parent / path).exists()
            or (path.endswith("/") and (std_dir.parent / path.rstrip("/")).exists())
            for path in container_check
        )
        if not has_container:
            return False
    return True


def analyze_gaps(std_dir: Path) -> dict[str, Any]:
    """Analyze the mumei std/ directory for missing components.

    This is the local-filesystem equivalent of the ``analyze_std_gaps``
    MCP tool in mumei's ``mcp_server.py``.

    Returns a dict with keys:
        dependency_graph, trusted_atoms, todo_comments, proposals
    """
    if not std_dir.exists():
        return {
            "dependency_graph": {},
            "trusted_atoms": [],
            "todo_comments": [],
            "proposals": [],
        }

    dependency_graph = _scan_std_imports(std_dir)
    trusted_atoms = _collect_trusted_atoms(std_dir)
    todo_comments = _collect_todo_comments(std_dir)

    existing_paths = set(dependency_graph.keys())

    proposals: list[dict[str, Any]] = []
    for rule in _STD_GAP_RULES:
        if not _evaluate_rule(rule, existing_paths, std_dir):
            continue
        proposals.append(
            {
                "name": rule["target"],
                "reason": rule["reason"],
                "depends_on": rule["depends_on"],
                "difficulty": rule["difficulty"],
            }
        )

    # Rank proposals: lower difficulty and fewer unmet deps rank higher.
    difficulty_weight = {"low": 0, "medium": 1, "high": 2}

    def _rank_key(p: dict[str, Any]) -> tuple[int, int]:
        diff = difficulty_weight.get(p["difficulty"], 3)
        unmet = sum(1 for dep in p["depends_on"] if dep not in existing_paths)
        return (diff, unmet)

    proposals.sort(key=_rank_key)
    for i, p in enumerate(proposals[:3], start=1):
        p["priority"] = i
    proposals = proposals[:3]

    return {
        "dependency_graph": dependency_graph,
        "trusted_atoms": trusted_atoms,
        "todo_comments": todo_comments,
        "proposals": proposals,
    }


# ---------------------------------------------------------------------------
# Spec generation from gap proposals
# ---------------------------------------------------------------------------


def generate_specs_from_gaps(
    gaps: dict[str, Any],
    max_count: int = 3,
) -> list[dict[str, Any]]:
    """Convert gap analysis proposals into forge task specs.

    Re-uses :func:`agent.propose.build_spec_from_proposal` for
    format compatibility with the existing forge runner.
    """
    proposals = gaps.get("proposals") or []
    if not isinstance(proposals, list):
        return []
    specs: list[dict[str, Any]] = []
    for idx, proposal in enumerate(proposals[:max_count], start=1):
        if not isinstance(proposal, dict):
            continue
        raw_priority = proposal.get("priority")
        spec = build_spec_from_proposal(
            proposal,
            priority=raw_priority if raw_priority is not None else idx,
        )
        specs.append(spec)
    return specs


# ---------------------------------------------------------------------------
# Blast radius check
# ---------------------------------------------------------------------------


def check_blast_radius(
    mumei_client: MumeiClient,
    mumei_repo_dir: Path,
    new_file_path: Path,
    code: str,
) -> dict[str, Any]:
    """Check whether adding *code* at *new_file_path* breaks existing std.

    Writes the new ``.mm`` file to *new_file_path*, then verifies every
    existing ``.mm`` file under ``std/``.  On completion the new file is
    removed so the caller decides what to persist.

    Returns::

        {"broken_files": [{"file": ..., "error": ...}], "all_passed": bool}
    """
    std_dir = mumei_repo_dir / "std"
    wrote_new = False
    result: dict[str, Any] = {"broken_files": [], "all_passed": True}

    try:
        # Write new file
        new_file_path.parent.mkdir(parents=True, exist_ok=True)
        new_file_path.write_text(code, encoding="utf-8")
        wrote_new = True

        # Verify every existing .mm file (excluding the new one)
        for mm_file in sorted(std_dir.rglob("*.mm")):
            if mm_file.resolve() == new_file_path.resolve():
                continue
            verify = mumei_client.verify(str(mm_file))
            if not verify["success"]:
                result["broken_files"].append(
                    {"file": str(mm_file), "error": verify.get("stderr", "")}
                )
        result["all_passed"] = len(result["broken_files"]) == 0
    finally:
        # Clean up: remove the new file so caller controls persistence
        if wrote_new and new_file_path.exists():
            try:
                new_file_path.unlink()
            except OSError:
                pass

    return result


# ---------------------------------------------------------------------------
# Self-healing for broken files
# ---------------------------------------------------------------------------


def attempt_heal(
    client: Any,
    model: str,
    broken_info: dict[str, Any],
    mumei_client: MumeiClient,
    max_retries: int = 3,
) -> bool:
    """Attempt to heal a broken ``.mm`` file using the fix strategy.

    Uses :func:`agent.strategies.fix_strategy.get_fix` to generate
    candidate fixes, then re-verifies.  Returns ``True`` if the file
    was successfully repaired.
    """
    from agent.strategies.fix_strategy import get_fix

    file_path = broken_info["file"]
    try:
        source_code = Path(file_path).read_text(encoding="utf-8")
    except OSError:
        logger.error("Cannot read broken file %s", file_path)
        return False

    for attempt in range(max_retries):
        verify = mumei_client.verify(file_path)
        if verify["success"]:
            return True

        error_log = verify.get("stderr", "") + verify.get("stdout", "")
        report_data = verify.get("report") or {}

        fixed_code = get_fix(
            client=client,
            model=model,
            source_code=source_code,
            error_log=error_log,
            report_data=report_data,
            mumei_client=mumei_client,
            source_path=file_path,
        )
        if not fixed_code or fixed_code == source_code:
            logger.warning(
                "Heal attempt %d/%d for %s produced no change",
                attempt + 1,
                max_retries,
                file_path,
            )
            continue

        # Write fixed code and re-verify
        Path(file_path).write_text(fixed_code, encoding="utf-8")
        source_code = fixed_code

    # Final check
    final = mumei_client.verify(file_path)
    return final["success"]


# ---------------------------------------------------------------------------
# Main proliferate loop
# ---------------------------------------------------------------------------


def proliferate(
    mumei_repo_dir: str | Path,
    *,
    max_proposals: int = 3,
    dry_run: bool = False,
    mumei_bin: str | None = None,
) -> list[dict[str, Any]]:
    """Run the autonomous proliferation loop.

    1. Analyze std/ gaps
    2. Generate forge task specs from proposals
    3. For each spec: generate code → blast-radius check → heal → publish

    Parameters
    ----------
    mumei_repo_dir:
        Path to the mumei repository (must contain ``std/``).
    max_proposals:
        Maximum number of proposals to process.
    dry_run:
        If True, skip git/PR operations and do not persist generated files.
    mumei_bin:
        Path or command for the mumei binary.

    Returns
    -------
    List of result dicts, one per proposal.
    """
    mumei_repo = Path(mumei_repo_dir).resolve()
    std_dir = mumei_repo / "std"

    if not std_dir.exists():
        logger.error("std/ directory not found at %s", std_dir)
        return [{"success": False, "reason": "std_dir_not_found"}]

    # Optional: measure initial health
    health_before = None
    try:
        from agent.std_health import measure_health as _measure_health

        config_for_health = AgentConfig()
        health_client = MumeiClient(mumei_bin or config_for_health.mumei_bin)
        health_before = _measure_health(health_client, std_dir)
        logger.info(
            "Initial health score: %.2f (%d/%d files verified)",
            health_before["health_score"],
            health_before["verified_files"],
            health_before["total_files"],
        )
    except Exception:
        logger.debug("Could not measure initial health", exc_info=True)

    # Step 1: Gap analysis
    logger.info("Step 1: Analyzing gaps in %s", std_dir)
    gaps = analyze_gaps(std_dir)
    if not gaps["proposals"]:
        logger.info("No proposals found — std/ is complete or no gaps detected")
        return [{"success": True, "reason": "no_proposals"}]

    logger.info(
        "Found %d proposal(s): %s",
        len(gaps["proposals"]),
        ", ".join(p["name"] for p in gaps["proposals"]),
    )

    # Step 2: Generate specs
    logger.info("Step 2: Generating forge task specs")
    specs = generate_specs_from_gaps(gaps, max_count=max_proposals)
    if not specs:
        return [{"success": True, "reason": "no_specs_generated"}]

    # Step 3: Process each spec
    config = AgentConfig()
    effective_mumei_bin = mumei_bin or config.mumei_bin
    mumei_client = MumeiClient(effective_mumei_bin)
    openai_client = config.create_client()

    results: list[dict[str, Any]] = []
    for spec in specs:
        spec_result: dict[str, Any] = {
            "spec": spec,
            "success": False,
        }
        target_file = spec.get("target_file", "unknown.mm")
        logger.info("Processing: %s", target_file)

        # 3a. Generate code
        try:
            code, verified = generate_code(
                client=openai_client,
                model=config.model,
                spec=spec,
                config_max_retries=config.max_retries,
                mumei_client=mumei_client,
            )
        except Exception as exc:
            logger.error("Code generation failed for %s: %s", target_file, exc)
            spec_result["reason"] = f"generation_error: {exc}"
            results.append(spec_result)
            continue

        if not code:
            logger.warning("No code generated for %s", target_file)
            spec_result["reason"] = "empty_code"
            results.append(spec_result)
            continue

        if not verified:
            logger.warning("Generated code for %s did not pass verification", target_file)
            spec_result["reason"] = "verification_failed"
            results.append(spec_result)
            continue

        spec_result["code"] = code
        spec_result["verified"] = verified

        # 3b. Blast radius check
        new_file_path = mumei_repo / target_file
        blast = check_blast_radius(mumei_client, mumei_repo, new_file_path, code)

        if blast["broken_files"]:
            logger.warning(
                "Blast radius check: %d file(s) broken by %s",
                len(blast["broken_files"]),
                target_file,
            )

            # 3c. Attempt to heal broken files
            # First, re-place the new file so healing operates in context
            new_file_path.parent.mkdir(parents=True, exist_ok=True)
            new_file_path.write_text(code, encoding="utf-8")

            all_healed = True
            for broken in blast["broken_files"]:
                healed = attempt_heal(
                    client=openai_client,
                    model=config.model,
                    broken_info=broken,
                    mumei_client=mumei_client,
                )
                if not healed:
                    logger.error(
                        "Could not heal %s — skipping proposal %s",
                        broken["file"],
                        target_file,
                    )
                    all_healed = False
                    break

            if not all_healed:
                # Rollback: remove the new file
                if new_file_path.exists():
                    new_file_path.unlink()
                spec_result["reason"] = "blast_radius_heal_failed"
                results.append(spec_result)
                continue

            # Remove the file again — publish will handle placement
            if new_file_path.exists():
                new_file_path.unlink()

        # 3d. Publish (or dry-run)
        if dry_run:
            logger.info("Dry run — skipping publish for %s", target_file)
            spec_result["success"] = True
            spec_result["dry_run"] = True
            results.append(spec_result)
            continue

        # Write spec to a temp file for publish()
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                json.dump(spec, tmp, indent=2, ensure_ascii=False)
                tmp_spec_path = tmp.name

            pub_result = publish(
                spec_path=tmp_spec_path,
                mumei_bin=effective_mumei_bin,
                repo_dir=str(mumei_repo),
                dry_run=False,
            )
            spec_result["publish_result"] = pub_result
            spec_result["success"] = pub_result.get("success", False)
            if pub_result.get("pr_url"):
                spec_result["pr_url"] = pub_result["pr_url"]
        except Exception as exc:
            logger.error("Publish failed for %s: %s", target_file, exc)
            spec_result["reason"] = f"publish_error: {exc}"
        finally:
            try:
                Path(tmp_spec_path).unlink(missing_ok=True)
            except Exception:
                pass

        results.append(spec_result)

    # Optional: measure final health
    if health_before is not None:
        try:
            health_after = _measure_health(health_client, std_dir)
            logger.info(
                "Final health score: %.2f (was %.2f, delta %+.2f)",
                health_after["health_score"],
                health_before["health_score"],
                health_after["health_score"] - health_before["health_score"],
            )
        except Exception:
            logger.debug("Could not measure final health", exc_info=True)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser(parser: argparse.ArgumentParser) -> None:
    """Add proliferate-specific arguments to *parser*."""
    parser.add_argument(
        "--mumei-repo",
        required=True,
        help="Path to the mumei repository (must contain std/)",
    )
    parser.add_argument(
        "--max-proposals",
        type=int,
        default=3,
        help="Maximum number of proposals to process (default: 3)",
    )
    parser.add_argument(
        "--mumei-bin",
        default=None,
        help="Path to the mumei binary (default: MUMEI_BIN env or 'mumei')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip git/PR operations and do not persist generated files",
    )


def main(args: argparse.Namespace) -> None:
    """Entry point for the proliferate subcommand."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    results = proliferate(
        mumei_repo_dir=args.mumei_repo,
        max_proposals=args.max_proposals,
        dry_run=args.dry_run,
        mumei_bin=args.mumei_bin,
    )

    succeeded = sum(1 for r in results if r.get("success"))
    total = len(results)
    print(f"\nproliferate: {succeeded}/{total} proposal(s) succeeded")

    for r in results:
        spec = r.get("spec", {})
        target = spec.get("target_file", r.get("reason", "?"))
        status = "OK" if r.get("success") else "FAIL"
        reason = r.get("reason", "")
        pr_url = r.get("pr_url", "")
        line = f"  [{status}] {target}"
        if reason:
            line += f" — {reason}"
        if pr_url:
            line += f" — PR: {pr_url}"
        print(line)

    if succeeded == 0 and total > 0:
        import sys

        sys.exit(1)
