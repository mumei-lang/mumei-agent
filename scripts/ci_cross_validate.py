#!/usr/bin/env python3
"""Run cross-validation in CI and optionally post the report to a PR."""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import json
import os
from pathlib import Path
import sys
from urllib import request

from agent.cross_validation import validate_code_to_spec, validate_spec_to_code
from agent.report_formatter import format_cross_validation_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CI cross-validation gate for specs and code.")
    parser.add_argument("--spec", required=True, help="Path to the natural-language spec file.")
    parser.add_argument("--code", required=True, help="Path to the implementation file.")
    parser.add_argument("--language", choices=["python", "rust", "go"], help="Implementation language.")
    parser.add_argument("--mode", choices=["spec-to-code", "code-to-spec", "both"], default="both")
    parser.add_argument("--lang", choices=["en", "ja"], default="en", help="Markdown report language.")
    parser.add_argument("--output", help="Write Markdown report to this file.")
    parser.add_argument("--json-output", help="Write structured JSON report to this file.")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM contract inference.")
    parser.add_argument("--no-mumei", action="store_true", help="Skip mumei verify.")
    parser.add_argument("--post-comment", action="store_true", help="Post the report as a GitHub PR comment.")
    parser.add_argument("--pr-number", help="Pull request number. Defaults to GITHUB_REF/GITHUB_EVENT_PATH.")
    parser.add_argument("--repo", help="GitHub repository, e.g. owner/repo. Defaults to GITHUB_REPOSITORY.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    spec_text = Path(args.spec).read_text(encoding="utf-8")
    results: list[object] = []
    if args.mode in {"spec-to-code", "both"}:
        results.append(
            validate_spec_to_code(
                spec_text,
                args.code,
                language=args.language,
                use_llm=not args.no_llm,
                run_mumei=not args.no_mumei,
                lang=args.lang,
            )
        )
    if args.mode in {"code-to-spec", "both"}:
        results.append(
            validate_code_to_spec(
                args.code,
                args.spec,
                language=args.language,
                use_llm=not args.no_llm,
                run_mumei=not args.no_mumei,
                lang=args.lang,
            )
        )

    markdown = _combined_markdown(results, args.lang)
    if args.output:
        Path(args.output).write_text(markdown + "\n", encoding="utf-8")
    else:
        print(markdown)

    if args.json_output:
        payload = [_result_payload(result) for result in results]
        Path(args.json_output).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.post_comment:
        repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
        pr_number = args.pr_number or _detect_pr_number()
        _post_pr_comment(repo, pr_number, markdown)

    failed = any(not bool(_result_payload(result).get("success")) for result in results)
    sys.exit(1 if failed else 0)


def _combined_markdown(results: list[object], lang: str) -> str:
    heading = "## Cross-Validation CI Report" if lang == "en" else "## Cross-Validation CI レポート"
    sections = [heading]
    for result in results:
        sections.append(format_cross_validation_report(result, lang="ja" if lang == "ja" else "en"))
    return "\n\n".join(sections)


def _result_payload(result: object) -> dict[str, object]:
    if is_dataclass(result) and not isinstance(result, type):
        value = asdict(result)
        return {str(key): item for key, item in value.items()}
    if isinstance(result, dict):
        return {str(key): item for key, item in result.items()}
    return {}


def _detect_pr_number() -> str:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path:
        try:
            payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        pull_request = payload.get("pull_request") if isinstance(payload, dict) else None
        if isinstance(pull_request, dict) and pull_request.get("number"):
            return str(pull_request["number"])
        if isinstance(payload, dict) and payload.get("number"):
            return str(payload["number"])
    ref = os.environ.get("GITHUB_REF", "")
    parts = ref.split("/")
    if len(parts) >= 3 and parts[1] == "pull":
        return parts[2]
    raise RuntimeError("--pr-number is required outside pull_request GitHub Actions events")


def _post_pr_comment(repo: str, pr_number: str, body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required to post a PR comment")
    if not repo:
        raise RuntimeError("--repo or GITHUB_REPOSITORY is required to post a PR comment")
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    payload = json.dumps({"body": body}).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        if response.status >= 300:
            raise RuntimeError(f"GitHub comment API returned HTTP {response.status}")


if __name__ == "__main__":
    main()
