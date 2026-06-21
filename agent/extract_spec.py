"""CLI for extracting Mumei forge task specs from natural language."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from agent.config import AgentConfig
from agent.metrics import Metrics
from agent.mumei_client import create_mumei_client
from agent.spec_extractor import extract_spec


def _mumei_literal_for_type(type_name: str) -> str:
    normalized = type_name.strip().lower()
    if normalized in {"bool", "boolean"}:
        return "true"
    if normalized in {"str", "string"}:
        return '""'
    return "0"


def _clean_contract_clause(value: object, default: str = "true") -> str:
    text = str(value or default).strip()
    return text[:-1].strip() if text.endswith(";") else text


def _atom_params(atom: dict) -> str:
    params = atom.get("inputs", atom.get("params", []))
    if not isinstance(params, list):
        return ""
    rendered = []
    for param in params:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "").strip()
        type_name = str(param.get("type") or "i64").strip() or "i64"
        if name:
            rendered.append(f"{name}: {type_name}")
    return ", ".join(rendered)


def _spec_to_contradiction_check_module(spec: dict) -> str:
    atoms = spec.get("atoms")
    if not isinstance(atoms, list) or not atoms:
        raise ValueError("spec must contain a non-empty atoms list")

    blocks: list[str] = []
    for index, atom in enumerate(atoms):
        if not isinstance(atom, dict):
            raise ValueError(f"atoms[{index}] must be an object")
        name = str(atom.get("name") or f"extracted_atom_{index}").strip()
        if not name:
            raise ValueError(f"atoms[{index}].name must be non-empty")
        return_type = str(atom.get("return_type") or "i64").strip() or "i64"
        requires = _clean_contract_clause(atom.get("requires"))
        ensures = _clean_contract_clause(atom.get("ensures"))
        default_value = _mumei_literal_for_type(return_type)
        blocks.append(
            "\n".join(
                [
                    f"trusted atom {name}({_atom_params(atom)}) -> {return_type} {{",
                    f"    requires: {requires};",
                    f"    ensures: {ensures};",
                    "    body: {",
                    f"        {default_value}",
                    "    }",
                    "}",
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def _natural_language_contradiction_report(verify_result: dict) -> str:
    report = verify_result.get("report")
    if isinstance(report, dict):
        details = report.get("contradiction_details") or report.get("error")
        if details:
            return str(details)
        feedback = report.get("structured_feedback")
        if isinstance(feedback, dict):
            for key in ("message", "details", "suggested_fix"):
                if feedback.get(key):
                    return str(feedback[key])
        failed = report.get("failed")
        failed_count = failed if isinstance(failed, int) else 0
        if report.get("status") == "failed" or failed_count > 0:
            count = str(failed_count) if failed_count else "one or more"
            return (
                "SpecValidation failed for the synthesized specification: "
                f"Mumei reported {count} failed atom(s) while checking extracted contracts. "
                "At least one extracted requires/ensures clause is unsatisfiable or internally inconsistent."
            )
    stderr = str(verify_result.get("stderr") or "").strip()
    stdout = str(verify_result.get("stdout") or "").strip()
    combined = "\n".join(part for part in [stderr, stdout] if part)
    if "Spec contradiction" in combined or "SpecValidation failed" in combined:
        return combined
    return ""


def _code_extensions_for_language(
    extension_map: Mapping[str, str],
    language: str | None,
) -> list[str]:
    if language in {None, "unknown"}:
        return sorted(extension_map)
    return sorted(
        extension
        for extension, mapped_language in extension_map.items()
        if mapped_language == language
    )


def _collect_code_files(
    source_dir: Path,
    extension_map: Mapping[str, str],
    language: str | None,
) -> list[Path]:
    extensions = set(_code_extensions_for_language(extension_map, language))
    if not extensions:
        return []
    return sorted(
        (
            path
            for path in source_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in extensions
        ),
        key=lambda path: path.relative_to(source_dir).as_posix(),
    )


def extract_spec_from_code_directory(
    config: AgentConfig,
    source_dir: Path,
    *,
    language: str | None = None,
    domain_hint: str = "",
    mumei_client=None,
    max_retries: int = 3,
    metrics: Metrics | None = None,
) -> dict[str, Any]:
    """Extract per-file specs from a source directory and merge them."""
    from agent.code_to_spec import CodeToSpecExtractor

    source_dir = source_dir.expanduser().resolve()
    if not source_dir.exists():
        raise ValueError(f"code_file does not exist: {source_dir}")
    if not source_dir.is_dir():
        raise ValueError(f"code_file is not a directory: {source_dir}")

    code_files = _collect_code_files(
        source_dir,
        CodeToSpecExtractor.EXTENSION_MAP,
        language,
    )
    if not code_files:
        raise ValueError(
            f"no supported source-code files found in directory: {source_dir}"
        )

    extractor = CodeToSpecExtractor(config)
    files: list[dict[str, Any]] = []
    natural_language_sections: list[str] = []
    for code_path in code_files:
        result = extractor.extract_from_file(
            code_path,
            language=language,
            domain_hint=domain_hint,
            mumei_client=mumei_client,
            max_retries=max_retries,
        )
        relative_path = code_path.relative_to(source_dir).as_posix()
        if not result.success or result.forge_task_spec is None:
            errors = "; ".join(result.errors) or "unknown error"
            raise ValueError(f"failed to extract spec from {relative_path}: {errors}")

        files.append(
            {
                "path": str(code_path),
                "relative_path": relative_path,
                "natural_language_spec": result.natural_language_spec,
                "detected_language": result.detected_language,
                "spec": result.forge_task_spec,
                "warnings": result.warnings,
            }
        )
        natural_language_sections.append(
            f"## Source file: {relative_path}\n{result.natural_language_spec}"
        )

    merged_natural_language = "\n\n".join(
        [
            "Merge the following source-file requirements into a single coherent "
            "Mumei forge task specification. Preserve cross-file relationships and "
            "avoid duplicate atoms.",
            *natural_language_sections,
        ]
    )
    client = config.create_client()
    merged_spec = extract_spec(
        client,
        config.model,
        merged_natural_language,
        domain_hint=domain_hint,
        mumei_client=mumei_client,
        max_retries=max_retries,
        metrics=metrics,
    )
    return {"files": files, "merged_spec": merged_spec}


def check_spec_contradiction_from_spec(spec: dict, mumei_client) -> dict:
    """Check extracted forge-task specs for direct contract contradictions."""
    module_source = _spec_to_contradiction_check_module(spec)
    with tempfile.TemporaryDirectory(prefix="mumei-spec-contradiction-") as tmp:
        tmp_path = Path(tmp)
        spec_path = tmp_path / "extracted_spec_contradiction.mm"
        report_dir = tmp_path / "report"
        spec_path.write_text(module_source, encoding="utf-8")
        verify_result = mumei_client.verify(str(spec_path), report_dir=str(report_dir))

    explanation = _natural_language_contradiction_report(verify_result)
    contradiction_found = not verify_result.get("success", False) and bool(explanation)
    if contradiction_found:
        natural_language_explanation = (
            "The extracted natural-language specification contains a direct contradiction. "
            + explanation
        )
    else:
        natural_language_explanation = (
            "No direct contradiction was detected in the extracted specification."
        )
    return {
        "contradiction_found": contradiction_found,
        "contradiction_type": "spec_internal" if contradiction_found else "",
        "natural_language_explanation": natural_language_explanation,
        "verification": verify_result,
    }


def _read_text(args: argparse.Namespace) -> str:
    """Read requirement text from CLI arguments."""
    if args.text is not None:
        return args.text
    try:
        return Path(args.text_file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: Failed to read --text-file: {exc}", file=sys.stderr)
        sys.exit(1)


def _safe_task_filename(spec: dict) -> str:
    task_id = str(spec.get("task_id") or "extracted-spec")
    safe = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in task_id
    ).strip(".-")
    return f"{safe or 'extracted-spec'}.json"


def _write_forge_task_spec(spec: dict, tasks_dir: str) -> Path:
    path = Path(tasks_dir).resolve() / _safe_task_filename(spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _run_forge(args: argparse.Namespace, config: AgentConfig, client, mumei, spec_path: Path) -> None:
    from agent.forge import MumeiForge

    tasks_dir = Path(args.forge_tasks_dir).resolve()
    mumei_repo = (
        Path(args.mumei_repo).resolve()
        if args.mumei_repo
        else Path(os.environ.get("MUMEI_REPO", ".")).resolve()
    )
    log_path = Path(args.forge_log_path).resolve() if args.forge_log_path else None
    forge = MumeiForge(
        config=None if args.forge_dry_run else config,
        mumei_client=mumei,
        mumei_repo_dir=mumei_repo,
        forge_tasks_dir=tasks_dir,
        log_path=log_path,
        openai_client=None if args.forge_dry_run else client,
    )
    results = forge.run(dry_run=args.forge_dry_run, single_task_path=spec_path)
    print(f"Forge task spec written to {spec_path}")
    for result in results:
        extra = f" ({result.error})" if result.error else ""
        print(f"Forge result: {result.task_id} {result.status}{extra}")
    if not args.forge_dry_run and any(result.status == "failed" for result in results):
        sys.exit(1)


def build_parser(parser=None):
    """Add extract-spec arguments to an argparse parser."""
    if parser is None:
        parser = argparse.ArgumentParser(
            description="Extract Mumei specifications from natural language text."
        )

    text_group = parser.add_mutually_exclusive_group(required=True)
    text_group.add_argument(
        "--text",
        type=str,
        help="Natural language requirement text",
    )
    text_group.add_argument(
        "--text-file",
        type=str,
        help="Path to a file containing natural language requirements",
    )
    text_group.add_argument(
        "--code-file",
        type=str,
        help="Path to a source-code file or directory to convert into natural language requirements",
    )
    parser.add_argument(
        "--code-language",
        choices=[
            "rust",
            "c",
            "go",
            "python",
            "javascript",
            "typescript",
            "java",
            "cpp",
            "unknown",
        ],
        default=None,
        help="Optional language override for --code-file",
    )
    parser.add_argument(
        "--domain",
        choices=[
            "financial",
            "compliance",
            "regtech",
            "security",
            "iot",
            "web",
            "data_structure",
            "math",
            "general",
        ],
        default="",
        help="Optional domain hint for safer specification extraction",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for the extracted forge task spec JSON",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate and verify .mm code after extracting the spec",
    )
    parser.add_argument(
        "--check-contradiction-only",
        action="store_true",
        help="Extract specs and run only direct contradiction detection; skip code generation",
    )
    parser.add_argument(
        "--generate-output",
        help="Output path for generated .mm code when --generate is set",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum spec extraction retry attempts",
    )
    parser.add_argument(
        "--max-generation-retries",
        type=int,
        default=None,
        help="Maximum code generation/self-healing retry attempts",
    )
    parser.add_argument(
        "--max-refinements",
        type=int,
        default=3,
        help="Maximum spec refinement attempts when --generate is set",
    )
    parser.add_argument(
        "--forge",
        action="store_true",
        help="Write the extracted spec to forge_tasks/ and run the forge pipeline",
    )
    parser.add_argument(
        "--forge-tasks-dir",
        default="forge_tasks",
        help="Directory where --forge writes the extracted task spec",
    )
    parser.add_argument(
        "--mumei-repo",
        default=None,
        help="Path to the mumei repo used by --forge",
    )
    parser.add_argument(
        "--forge-dry-run",
        action="store_true",
        help="Preview the forge plan after extraction without generating code",
    )
    parser.add_argument(
        "--forge-log-path",
        default=None,
        help="Path to forge_log.json when --forge runs",
    )
    return parser


def main(args=None):
    """Run natural-language spec extraction."""
    if args is None:
        parser = build_parser()
        args = parser.parse_args()

    if args.generate and not args.generate_output:
        print("Error: --generate-output is required when --generate is set.", file=sys.stderr)
        sys.exit(1)
    if args.generate and args.check_contradiction_only:
        print(
            "Error: --check-contradiction-only cannot be combined with --generate.",
            file=sys.stderr,
        )
        sys.exit(1)

    config = AgentConfig()
    client = config.create_client()
    mumei = create_mumei_client(config.mumei_bin)
    domain_hint = "" if args.domain == "general" else args.domain
    directory_result: dict[str, Any] | None = None

    try:
        if args.code_file:
            from agent.code_to_spec import CodeToSpecExtractor

            source_path = Path(args.code_file).expanduser()
            if source_path.is_dir():
                metrics = Metrics()
                directory_result = extract_spec_from_code_directory(
                    config,
                    source_path,
                    language=args.code_language,
                    domain_hint=domain_hint,
                    mumei_client=mumei,
                    max_retries=args.max_retries,
                    metrics=metrics,
                )
                for file_result in directory_result["files"]:
                    for warning in file_result["warnings"]:
                        print(
                            f"Warning ({file_result['relative_path']}): {warning}",
                            file=sys.stderr,
                        )
                print(
                    f"Code files: {len(directory_result['files'])}",
                    file=sys.stderr,
                )
                natural_language = "\n\n".join(
                    file_result["natural_language_spec"]
                    for file_result in directory_result["files"]
                )
                forge_spec = directory_result["merged_spec"]
            else:
                code_result = CodeToSpecExtractor(config).extract_from_file(
                    source_path,
                    language=args.code_language,
                    domain_hint=domain_hint,
                    mumei_client=mumei,
                    max_retries=args.max_retries,
                )
                for warning in code_result.warnings:
                    print(f"Warning: {warning}", file=sys.stderr)
                if not code_result.success or code_result.forge_task_spec is None:
                    print(
                        "Error: failed to extract spec from code: "
                        + "; ".join(code_result.errors),
                        file=sys.stderr,
                    )
                    sys.exit(1)
                print(
                    f"Code language: {code_result.detected_language}",
                    file=sys.stderr,
                )
                natural_language = code_result.natural_language_spec
                forge_spec = code_result.forge_task_spec
                metrics = Metrics()
        else:
            natural_language = _read_text(args)
            metrics = Metrics()
            forge_spec = extract_spec(
                client,
                config.model,
                natural_language,
                domain_hint=domain_hint,
                mumei_client=mumei,
                max_retries=args.max_retries,
                metrics=metrics,
            )
            print(
                f"Extraction metrics: attempts={metrics.extraction_attempts}, "
                f"successes={metrics.extraction_successes}",
                file=sys.stderr,
            )

        if args.check_contradiction_only:
            contradiction_report = check_spec_contradiction_from_spec(forge_spec, mumei)
            if directory_result is not None:
                output_payload = {
                    "files": directory_result["files"],
                    "merged_spec": forge_spec,
                    "spec": forge_spec,
                    **contradiction_report,
                }
            else:
                output_payload = {
                    "spec": forge_spec,
                    **contradiction_report,
                }
            Path(args.output).write_text(
                json.dumps(output_payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            print(contradiction_report["natural_language_explanation"])
            print(f"Contradiction report written to {args.output}")
            return

        if args.generate:
            from agent.generate import _normalize_forge_task_spec
            from agent.strategies.generate_strategy import generate_code
            from agent.strategies.spec_refinement import run_refinement_loop

            max_generation_retries = (
                args.max_generation_retries
                if args.max_generation_retries is not None
                else config.max_retries
            )
            code, verified, spec = run_refinement_loop(
                client,
                config.model,
                _normalize_forge_task_spec(forge_spec),
                generate_code,
                max_refinements=args.max_refinements,
                config_max_retries=max_generation_retries,
                mumei_client=mumei,
                metrics=metrics,
            )
        else:
            code = ""
            verified = False
            spec = forge_spec
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    output_payload: dict[str, Any] | None = None
    if directory_result is not None:
        output_payload = {
            "files": directory_result["files"],
            "merged_spec": spec,
        }

    Path(args.output).write_text(
        json.dumps(output_payload or spec, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Extracted spec written to {args.output}")

    if args.forge:
        # Use the original (unnormalized) forge task spec, which is required
        # to have `atoms`, `task_id`, and `mode` for the forge pipeline.
        forge_spec_path = _write_forge_task_spec(forge_spec, args.forge_tasks_dir)
        _run_forge(args, config, client, mumei, forge_spec_path)

    if args.generate:
        if not code:
            print("Error: Generation failed — no code produced.", file=sys.stderr)
            sys.exit(1)
        Path(args.generate_output).write_text(code, encoding="utf-8")
        if verified:
            print(f"Generated verified code written to {args.generate_output}")
        else:
            print(
                f"Warning: Generated code written to {args.generate_output} "
                "but verification failed — output is NOT verified.",
                file=sys.stderr,
            )
            sys.exit(1)
