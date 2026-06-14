"""Allow running as `python -m agent` with subcommands."""
import sys

_SUBCOMMANDS = {
    "heal",
    "generate",
    "publish",
    "forge",
    "propose",
    "analyze-std-gaps",
    "proliferate",
    "health",
    "extract-spec",
    "validate-spec",
    "validate-code",
    "validate-spec-to-code",
    "validate-code-to-spec",
    "self-correct",
    "mcp-server",
    "check-spec-health",
    "verify-foreign",
    "migrate-suggest",
    "cross-validate",
}


def main() -> None:
    """Route to heal or generate subcommand."""
    # Determine the subcommand by inspecting the first positional arg
    # *before* argparse runs, so that unknown positional args (e.g.
    # `python -m agent examples/sword_test.mm`) fall through to heal
    # mode instead of being rejected as invalid subcommand choices.
    argv = sys.argv[1:]
    command = argv[0] if argv and argv[0] in _SUBCOMMANDS else None

    if command == "forge":
        import argparse
        from agent.forge import build_parser as forge_build_parser, main as forge_main

        parser = argparse.ArgumentParser(
            prog="python -m agent forge",
            description="Autonomous forge mode: extend the mumei std library "
                        "with verified atoms from task specs.",
        )
        forge_build_parser(parser)
        args = parser.parse_args(argv[1:])
        forge_main(args)
    elif command == "propose":
        import argparse
        from agent.propose import build_parser as propose_build_parser, main as propose_main

        parser = argparse.ArgumentParser(
            prog="python -m agent propose",
            description=(
                "Generate forge task specs from analyze_std_gaps output "
                "(SI-5 Phase 2-A)."
            ),
        )
        propose_build_parser(parser=parser)
        args = parser.parse_args(argv[1:])
        propose_main(args)
    elif command == "analyze-std-gaps":
        import argparse
        from agent.analyze_std_gaps import (
            build_parser as analyze_build_parser,
            main as analyze_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent analyze-std-gaps",
            description="Analyze vStd roadmap gap coverage for forge automation.",
        )
        analyze_build_parser(parser=parser)
        args = parser.parse_args(argv[1:])
        analyze_main(args)
    elif command == "publish":
        import argparse
        from agent.publish import build_parser, main as publish_main

        parser = argparse.ArgumentParser(
            prog="python -m agent publish",
            description="Autonomous delivery: generate → verify → emit wrappers → PR",
        )
        build_parser(parser=parser)
        args = parser.parse_args(argv[1:])
        publish_main(args)
    elif command == "generate":
        import argparse
        from agent.generate import build_parser, main as generate_main

        parser = argparse.ArgumentParser(
            prog="python -m agent generate",
            description="Generate verified Mumei code from a JSON specification",
        )
        # Re-use the generate parser definition (adds --spec, --output, etc.)
        build_parser(parser=parser)
        args = parser.parse_args(argv[1:])
        generate_main(args)
    elif command == "proliferate":
        import argparse
        from agent.proliferate import build_parser as prolif_build_parser, main as prolif_main

        parser = argparse.ArgumentParser(
            prog="python -m agent proliferate",
            description=(
                "Autonomous proliferation loop: analyze gaps → spec → "
                "generate → blast-radius check → heal → PR (SI-5 Phase 2-C)."
            ),
        )
        prolif_build_parser(parser)
        args = parser.parse_args(argv[1:])
        prolif_main(args)
    elif command == "health":
        import argparse
        from agent.std_health import build_parser as health_build_parser, main as health_main

        parser = argparse.ArgumentParser(
            prog="python -m agent health",
            description=(
                "Measure proof health metrics for the mumei std library "
                "(SI-5 Phase 3-A)."
            ),
        )
        health_build_parser(parser)
        args = parser.parse_args(argv[1:])
        health_main(args)
    elif command == "extract-spec":
        import argparse
        from agent.extract_spec import build_parser as extract_build_parser, main as extract_main

        parser = argparse.ArgumentParser(
            prog="python -m agent extract-spec",
            description=(
                "Extract Mumei specifications from natural language text. "
                "Optionally generate and verify code in one step."
            ),
        )
        extract_build_parser(parser=parser)
        args = parser.parse_args(argv[1:])
        extract_main(args)
    elif command == "validate-spec":
        import argparse
        from agent.cross_validation import (
            build_validate_spec_parser,
            main_validate_spec,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent validate-spec",
            description="Validate natural-language specifications for logical health.",
        )
        build_validate_spec_parser(parser)
        args = parser.parse_args(argv[1:])
        main_validate_spec(args)
    elif command == "validate-code":
        import argparse
        from agent.cross_validation import (
            build_validate_code_parser,
            main_validate_code,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent validate-code",
            description="Infer and verify contracts from foreign-language code.",
        )
        build_validate_code_parser(parser)
        args = parser.parse_args(argv[1:])
        main_validate_code(args)
    elif command == "validate-spec-to-code":
        import argparse
        from agent.cross_validation import (
            build_validate_spec_to_code_parser,
            main_validate_spec_to_code,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent validate-spec-to-code",
            description="Detect missing implementation constraints by comparing specs to code.",
        )
        build_validate_spec_to_code_parser(parser)
        args = parser.parse_args(argv[1:])
        main_validate_spec_to_code(args)
    elif command == "validate-code-to-spec":
        import argparse
        from agent.cross_validation import (
            build_validate_code_to_spec_parser,
            main_validate_code_to_spec,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent validate-code-to-spec",
            description="Detect spec drift by comparing changed code to specs.",
        )
        build_validate_code_to_spec_parser(parser)
        args = parser.parse_args(argv[1:])
        main_validate_code_to_spec(args)
    elif command == "self-correct":
        import argparse
        from agent.self_correction import (
            build_self_correct_parser,
            main_self_correct,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent self-correct",
            description="Run the P9-F self-correction protocol.",
        )
        build_self_correct_parser(parser)
        args = parser.parse_args(argv[1:])
        main_self_correct(args)
    elif command == "check-spec-health":
        import argparse
        from agent.strategies.spec_health_strategy import (
            build_parser as spec_health_build_parser,
            main as spec_health_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent check-spec-health",
            description=(
                "Check a Mumei spec for contradictions, over-constraints, "
                "and vacuity."
            ),
        )
        spec_health_build_parser(parser)
        args = parser.parse_args(argv[1:])
        spec_health_main(args)
    elif command == "verify-foreign":
        import argparse
        from agent.strategies.foreign_code_strategy import (
            build_parser as foreign_code_build_parser,
            main as foreign_code_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent verify-foreign",
            description="Extract foreign-code contracts and verify them as Mumei atoms.",
        )
        foreign_code_build_parser(parser)
        args = parser.parse_args(argv[1:])
        foreign_code_main(args)
    elif command == "migrate-suggest":
        import argparse
        from dataclasses import asdict
        import json
        from pathlib import Path

        from agent.cross_validation import validate_foreign_code
        from agent.mm_migration_advisor import suggest_migration_for_file

        parser = argparse.ArgumentParser(
            prog="python -m agent migrate-suggest",
            description="Generate .mm migration skeletons for functions with verification issues.",
        )
        parser.add_argument("--code-file", required=True, help="Path to source code file.")
        parser.add_argument(
            "--language",
            choices=["python", "rust", "typescript"],
            required=True,
            help="Source language.",
        )
        parser.add_argument("--issues-json", default="[]", help="JSON issues array.")
        parser.add_argument("--output", help="Optional output directory for .mm skeletons.")
        args = parser.parse_args(argv[1:])

        code_path = Path(args.code_file).expanduser().resolve()
        code = code_path.read_text(encoding="utf-8")
        try:
            issues = json.loads(args.issues_json)
        except json.JSONDecodeError as exc:
            print(f"Error: failed to parse --issues-json: {exc}", file=sys.stderr)
            sys.exit(2)
        if not isinstance(issues, list):
            print("Error: --issues-json must be a JSON array.", file=sys.stderr)
            sys.exit(2)

        validation_result: dict[str, object] = {"issues": issues}
        if not issues and args.language in {"python", "rust"}:
            validation = validate_foreign_code(
                code,
                args.language,
                use_llm=False,
                run_mumei=False,
            )
            validation_result = asdict(validation)
        hints = suggest_migration_for_file(str(code_path), args.language, validation_result)
        if args.output:
            output_dir = Path(args.output).expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            for hint in hints:
                (output_dir / f"{hint.function_name}.mm").write_text(
                    hint.skeleton + "\n",
                    encoding="utf-8",
                )
        print(json.dumps({"migration_hints": [asdict(hint) for hint in hints]}, indent=2))
    elif command == "cross-validate":
        import argparse
        from agent.strategies.cross_validation_strategy import (
            CrossValidator,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent cross-validate",
            description=(
                "Cross-validate a Mumei spec (.mm) against implementation code. "
                "Detects semantic consistency gaps and spec coverage."
            ),
        )
        parser.add_argument("spec", help="Path to the .mm specification file")
        parser.add_argument("impl", help="Path to the implementation source file")
        parser.add_argument(
            "--language", "-l", default="",
            help="Implementation language (python/rust/typescript). Inferred from extension if omitted.",
        )
        parser.add_argument(
            "--old-cert", default=None,
            help="Path to old proof certificate for drift detection",
        )
        parser.add_argument(
            "--new-cert", default=None,
            help="Path to new proof certificate for drift detection",
        )
        parser.add_argument("--json", action="store_true", help="Output as JSON")
        args = parser.parse_args(argv[1:])

        import json as _json
        from pathlib import Path as _Path

        validator = CrossValidator()

        # Language inference
        lang = args.language
        if not lang:
            ext_map = {".py": "python", ".rs": "rust", ".ts": "typescript", ".tsx": "typescript"}
            lang = ext_map.get(_Path(args.impl).suffix.lower(), "")
            if not lang:
                print(f"Cannot infer language from extension; use --language", file=sys.stderr)
                sys.exit(1)

        report = validator.validate_spec_vs_impl(
            spec_path=args.spec, impl_path=args.impl, language=lang,
        )

        # Optional drift detection
        if args.old_cert and args.new_cert:
            old_cert = _json.loads(_Path(args.old_cert).read_text())
            new_cert = _json.loads(_Path(args.new_cert).read_text())
            drift = validator.detect_spec_drift(old_cert, new_cert)
            report.drift_detected = drift.drift_detected

        if args.json:
            print(_json.dumps(report.to_dict(), indent=2))
        else:
            print(f"Coverage: {report.coverage_ratio:.1%}")
            if report.uncovered_atoms:
                print(f"Uncovered atoms: {report.uncovered_atoms}")
            if report.spec_stronger_than_impl:
                print(f"Spec stronger than impl: {report.spec_stronger_than_impl}")
            if report.impl_stronger_than_spec:
                print(f"Impl stronger than spec: {report.impl_stronger_than_spec}")
            if report.drift_detected:
                print("⚠️  Spec drift detected!")
            if report.is_consistent:
                print("✅ Spec and implementation are consistent.")
    elif command == "mcp-server":
        # P10 — expose forge / heal / health / propose as MCP tools.
        # Any extra positional/optional args are ignored: FastMCP's
        # stdio transport does not take CLI flags.
        #
        # ``mcp[cli]`` is an optional extra; surface a clear hint when
        # the user hasn't installed it instead of a bare ImportError.
        try:
            from agent.mcp_server import main as mcp_main
        except ImportError as exc:
            print(
                f"error: mcp-server requires the 'mcp' extra ({exc}).\n"
                "Install with: pip install 'mumei-agent[mcp]'",
                file=sys.stderr,
            )
            sys.exit(1)

        mcp_main()
    elif command == "heal":
        from agent.self_healing import main as heal_main
        # Strip the 'heal' subcommand so self_healing's own argparse
        # sees only its arguments (e.g. ['agent', 'file.mm', ...]).
        sys.argv = [sys.argv[0]] + argv[1:]
        heal_main()
    else:
        # Backward compatibility: no subcommand means heal mode
        # (e.g. `python -m agent examples/sword_test.mm`)
        from agent.self_healing import main as heal_main
        heal_main()

if __name__ == "__main__":
    main()
