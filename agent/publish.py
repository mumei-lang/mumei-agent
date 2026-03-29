"""Autonomous delivery pipeline: generate → verify → emit wrappers → PR.

This module implements the ``--publish`` mode for mumei-agent.  It
orchestrates the full autonomous delivery flow:

1. Load a spec JSON
2. Call ``generate_code()`` to produce a verified ``.mm`` file
3. Call ``mumei_client.verify()`` to confirm verification passes
4. Call ``mumei_client.build_with_emit()`` for each target
   (``c-header``, ``rust-wrapper``, ``python-wrapper``)
5. Create a git branch ``auto/<module_name>``
6. Git add + commit the generated files
7. Create a PR via the GitHub API

The emit targets generate **FFI glue code** (not transpiled code):
- ``c-header``: generates ``.h`` files
- ``rust-wrapper``: generates Rust ``extern "C"`` bindings + safe wrappers
- ``python-wrapper``: generates ctypes-based Python wrappers
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from agent.config import AgentConfig
from agent.mumei_client import MumeiClient
from agent.strategies.generate_strategy import generate_code

logger = logging.getLogger(__name__)

_EMIT_TARGETS = ("c-header", "rust-wrapper", "python-wrapper")


def _git(args: list[str], cwd: str | Path) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the result."""
    cmd = ["git", *args]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd))


def _create_github_pr(
    owner: str,
    repo: str,
    title: str,
    head: str,
    base: str,
    body: str,
    token: str,
) -> dict:
    """Create a pull request via the GitHub API.

    Returns the parsed JSON response from the API.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    payload = json.dumps({
        "title": title,
        "head": head,
        "base": base,
        "body": body,
    }).encode()
    req = Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as exc:
        error_body = exc.read().decode() if exc.fp else ""
        logger.error("GitHub API error %s: %s", exc.code, error_body)
        raise


def publish(
    spec_path: str,
    *,
    mumei_bin: str = "mumei",
    output_dir: str = "katana",
    repo_dir: str | None = None,
    base_branch: str = "develop",
    github_owner: str | None = None,
    github_repo: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Run the full publish pipeline.

    Parameters
    ----------
    spec_path:
        Path to the spec JSON file.
    mumei_bin:
        Path or command for the mumei binary.
    output_dir:
        Output directory for build artifacts.
    repo_dir:
        Working directory for git operations (defaults to cwd).
    base_branch:
        Base branch for the PR.
    github_owner:
        GitHub repository owner (for PR creation).
    github_repo:
        GitHub repository name (for PR creation).
    dry_run:
        If True, skip git operations and PR creation.

    Returns
    -------
    dict with keys: success, generated_file, artifacts, pr_url
    """
    result: dict = {
        "success": False,
        "generated_file": None,
        "artifacts": [],
        "pr_url": None,
    }

    # 1. Load spec
    with open(spec_path) as f:
        spec = json.load(f)

    module_name = spec.get("module_name", spec.get("name", "module"))
    logger.info("Publishing module: %s", module_name)

    # 2. Generate code
    config = AgentConfig()
    client = MumeiClient(mumei_bin)
    openai_client = config.create_client()

    code, verified = generate_code(
        client=openai_client,
        model=config.model,
        spec=spec,
        config_max_retries=config.max_retries,
        mumei_client=client,
    )
    if not code:
        logger.error("Code generation failed — no code produced")
        result["generation_error"] = "empty code"
        return result

    generated_file = f"{module_name}.mm"
    with open(generated_file, "w", encoding="utf-8") as f:
        f.write(code)
    result["generated_file"] = generated_file
    result["verified_at_generation"] = verified
    logger.info("Generated: %s (verified=%s)", generated_file, verified)

    # 3. Verify
    verify_result = client.verify(generated_file)
    if not verify_result["success"]:
        logger.error("Verification failed: %s", verify_result.get("stderr", ""))
        result["verify_error"] = verify_result
        return result

    logger.info("Verification passed")

    # 4. Build with each emit target
    artifacts = []
    for target in _EMIT_TARGETS:
        emit_result = client.build_with_emit(generated_file, target, output_dir)
        artifacts.append({
            "target": target,
            "success": emit_result["success"],
            "stdout": emit_result["stdout"],
        })
        if emit_result["success"]:
            logger.info("Emitted %s successfully", target)
        else:
            logger.warning("Emit %s failed: %s", target, emit_result["stderr"])

    result["artifacts"] = artifacts

    if dry_run:
        logger.info("Dry run — skipping git operations and PR creation")
        result["success"] = True
        return result

    # 5. Git operations
    cwd = Path(repo_dir) if repo_dir else Path.cwd()
    branch_name = f"auto/{module_name}"

    _git(["checkout", "-b", branch_name], cwd=cwd)
    _git(["add", generated_file], cwd=cwd)
    # Add any output artifacts
    _git(["add", output_dir], cwd=cwd)

    commit_msg = (
        f"feat: auto-generated verified module `{module_name}`\n\n"
        f"Generated by mumei-agent publish pipeline.\n"
        f"Source spec: {spec_path}\n"
        f"Emit targets: {', '.join(_EMIT_TARGETS)}"
    )
    _git(["commit", "-m", commit_msg], cwd=cwd)
    _git(["push", "origin", branch_name], cwd=cwd)

    # 6. Create PR
    github_token = os.environ.get("GITHUB_TOKEN", "")
    owner = github_owner or os.environ.get("GITHUB_OWNER", "")
    repo = github_repo or os.environ.get("GITHUB_REPO", "")

    if not github_token or not owner or not repo:
        logger.warning(
            "Missing GITHUB_TOKEN / GITHUB_OWNER / GITHUB_REPO — "
            "skipping PR creation"
        )
        result["success"] = True
        return result

    pr_body = (
        f"## Auto-generated verified module: `{module_name}`\n\n"
        f"Generated by `mumei-agent --publish` from `{spec_path}`.\n\n"
        f"### Emit targets\n"
        + "\n".join(
            f"- {'✅' if a['success'] else '❌'} `{a['target']}`"
            for a in artifacts
        )
        + "\n\n"
        f"### FFI Note\n"
        f"The `rust-wrapper` and `python-wrapper` emit targets generate "
        f"**FFI glue code**, not transpiled source. They produce `extern \"C\"` "
        f"bindings / ctypes wrappers for calling the compiled mumei binary."
    )

    try:
        pr = _create_github_pr(
            owner=owner,
            repo=repo,
            title=f"feat: verified module `{module_name}` (auto-generated)",
            head=branch_name,
            base=base_branch,
            body=pr_body,
            token=github_token,
        )
        result["pr_url"] = pr.get("html_url")
        logger.info("PR created: %s", result["pr_url"])
    except Exception as exc:
        logger.exception("Failed to create PR")
        result["pr_error"] = str(exc)

    result["success"] = True
    return result


def build_parser(parser: "argparse.ArgumentParser") -> None:
    """Add publish-specific arguments to an argparse parser."""
    import argparse  # noqa: F811

    parser.add_argument(
        "--spec",
        required=True,
        help="Path to the spec JSON file",
    )
    parser.add_argument(
        "--mumei-bin",
        default="mumei",
        help="Path to the mumei binary (default: mumei)",
    )
    parser.add_argument(
        "--output",
        default="katana",
        help="Output directory for build artifacts (default: katana)",
    )
    parser.add_argument(
        "--repo-dir",
        default=None,
        help="Working directory for git operations (default: cwd)",
    )
    parser.add_argument(
        "--base-branch",
        default="develop",
        help="Base branch for the PR (default: develop)",
    )
    parser.add_argument(
        "--github-owner",
        default=None,
        help="GitHub repository owner (or set GITHUB_OWNER env var)",
    )
    parser.add_argument(
        "--github-repo",
        default=None,
        help="GitHub repository name (or set GITHUB_REPO env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip git operations and PR creation",
    )


def main(args: "argparse.Namespace") -> None:
    """Entry point for the publish subcommand."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    result = publish(
        spec_path=args.spec,
        mumei_bin=args.mumei_bin,
        output_dir=args.output,
        repo_dir=args.repo_dir,
        base_branch=args.base_branch,
        github_owner=args.github_owner,
        github_repo=args.github_repo,
        dry_run=args.dry_run,
    )

    if result["success"]:
        print(f"\n✅ Publish pipeline completed for: {result['generated_file']}")
        if result.get("pr_url"):
            print(f"   PR: {result['pr_url']}")
    else:
        print("\n❌ Publish pipeline failed", file=sys.stderr)
        sys.exit(1)
