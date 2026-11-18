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
    "harness-ablation",
    "health",
    "scale-report",
    "audit",
    "extract-spec",
    "validate-spec",
    "validate-code",  # deprecated verify-foreign is integrated here.
    "validate-spec-to-code",
    "validate-code-to-spec",
    "verify-conformance",
    "verify-traceability",
    "self-correct",
    "mcp-server",
    "check-spec-health",
    "migrate-suggest",
    "cross-validate",
    "harvest-tests",
    "observe-tests",
    "config",
    "go-summaries",
    "go-summaries-check",
    "go-summaries-reuse",
    "go-summaries-accept",
    "go-summaries-attempt",
    "go-summaries-reuse-attempt",
    "summaries-plan",
    "rust-summaries",
    "rust-summaries-accept",
    "rust-summaries-check",
    "rust-summaries-reuse",
    "rust-summaries-attempt",
    "rust-summaries-reuse-attempt",
    "ts-summaries",
    "ts-summaries-accept",
    "ts-summaries-check",
    "ts-summaries-reuse",
    "ts-summaries-attempt",
    "ts-summaries-reuse-attempt",
    "sol-summaries",
    "sol-summaries-accept",
    "sol-summaries-check",
    "sol-summaries-reuse",
    "sol-summaries-attempt",
    "sol-summaries-reuse-attempt",
    "evidence-check",
    "evidence-check-accept",
    "evidence-check-list",
    "evidence-check-consistency",
    "evidence-acceptance-eval",
    "signature-eval",
    "signature-verify",
    "recovery-eval",
    "freshness-eval",
    "binding-eval",
    "evidence-compare",
    "evidence-identity-check",
    "evidence-producer-check",
    "verify-attempt",
    "verify-recheck",
    "verify-accept",
    "verify-schedule",
    "native-attempt",
    "native-recheck",
    "native-accept",
    "native-artifact-recheck",
    "native-exit-status-recheck",
    "native-exit-status-accept",
    "native-stdout-recheck",
    "native-stdout-accept",
    "native-stderr-recheck",
    "native-stderr-accept",
    "native-check",
    "native-evidence-accept",
    "native-source-recheck",
    "native-evidence-recheck",
}


def main() -> None:
    """Route to heal or generate subcommand."""
    # Determine the subcommand by inspecting the first positional arg
    # *before* argparse runs, so that unknown positional args (e.g.
    # `python -m agent examples/sword_test.mm`) fall through to heal
    # mode instead of being rejected as invalid subcommand choices.
    argv = sys.argv[1:]
    aliases = {
        "verify-foreign": "validate-code",
    }
    command = None
    if argv:
        if argv[0] in _SUBCOMMANDS or argv[0] in aliases:
            command = aliases.get(argv[0], argv[0])

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
    elif command == "harness-ablation":
        import argparse
        from agent.harness_ablation import (
            build_parser as ablation_build_parser,
            main as ablation_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent harness-ablation",
            description=(
                "Compare harness_metrics aggregates across --harness-profile "
                "runs against a baseline (module ablation report)."
            ),
        )
        ablation_build_parser(parser)
        args = parser.parse_args(argv[1:])
        ablation_main(args)
    elif command == "scale-report":
        import argparse
        from agent.scale_report import (
            build_parser as scale_build_parser,
            main as scale_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent scale-report",
            description=(
                "Report large-scale composability and trust-surface measurements "
                "through the fixed verification_status / verification_violations / "
                "next_steps keys."
            ),
        )
        scale_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(scale_main(args))
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
    elif command == "audit":
        import argparse
        from agent.audit import build_parser as audit_build_parser, main as audit_main

        parser = argparse.ArgumentParser(
            prog="python -m agent audit",
            description=(
                "Audit existing code by extracting specs, verifying contracts, "
                "emitting cross_validation_gaps, and optionally producing migration_hints."
            ),
        )
        audit_build_parser(parser)
        args = parser.parse_args(argv[1:])
        audit_main(args)
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
            description="Infer and verify contracts from existing code (Python, Rust, TypeScript, Go, Solidity).",
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
            description=(
                "Detect missing implementation constraints and report the "
                "spec constraint to code line relationship."
            ),
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
    elif command == "verify-conformance":
        import argparse
        from agent.verify_conformance import (
            build_parser as conformance_build_parser,
            main as conformance_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent verify-conformance",
            description="Return structured JSON for natural-language spec to code conformance.",
        )
        conformance_build_parser(parser)
        args = parser.parse_args(argv[1:])
        conformance_main(args)
    elif command == "verify-traceability":
        import argparse
        from agent.verify_traceability import (
            build_parser as traceability_build_parser,
            main as traceability_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent verify-traceability",
            description="Return structured JSON for bidirectional spec/code traceability.",
        )
        traceability_build_parser(parser)
        args = parser.parse_args(argv[1:])
        traceability_main(args)
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
            choices=["python", "rust", "typescript", "go"],
            required=True,
            help="Source language.",
        )
        parser.add_argument("--issues-json", default="[]", help="JSON issues array.")
        parser.add_argument("--output", help="Optional output directory for .mm skeletons.")
        parser.add_argument(
            "--clause-labels",
            action="store_true",
            help="Emit requires clause labels from issues that carry required_contracts (pass them via --issues-json); needs a mumei build with clause-label support (v0.6.21 or later)",
        )
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
        if not issues and args.language in {"python", "rust", "typescript", "go"}:
            validation = validate_foreign_code(
                code,
                args.language,
                use_llm=False,
                run_mumei=False,
            )
            validation_result = asdict(validation)
        hints = suggest_migration_for_file(
            str(code_path),
            args.language,
            validation_result,
            clause_labels=args.clause_labels,
        )
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
            help="Implementation language (python/rust/typescript/go/solidity). Inferred from extension if omitted.",
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
            ext_map = {
                ".py": "python",
                ".rs": "rust",
                ".ts": "typescript",
                ".tsx": "typescript",
                ".go": "go",
                ".sol": "solidity",
            }
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
    elif command == "harvest-tests":
        from agent.test_harvest import build_parser, main as harvest_main

        parser = build_parser()
        args = parser.parse_args(argv[1:])
        raise SystemExit(harvest_main(args))
    elif command == "observe-tests":
        from agent.observe_tests import build_parser, main as observe_tests_main

        parser = build_parser()
        args = parser.parse_args(argv[1:])
        raise SystemExit(observe_tests_main(args))
    elif command == "config":
        import argparse
        from agent.config_report import build_parser, main as config_main

        parser = argparse.ArgumentParser(
            prog="python -m agent config",
            description="Show effective settings and where each value comes from",
        )
        build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(config_main(args))
    elif command == "go-summaries":
        import argparse
        from agent.go_summaries import (
            build_parser as go_summaries_build_parser,
            main as go_summaries_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent go-summaries",
            description=(
                "Run a provisioned go-types helper on declared Go sources "
                "and print the summary manifest JSON."
            ),
        )
        go_summaries_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(go_summaries_main(args))
    elif command == "go-summaries-check":
        import argparse
        from agent.go_summaries import (
            build_check_parser as go_summaries_check_build_parser,
            main_check as go_summaries_check_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent go-summaries-check",
            description=(
                "Run a provisioned go-types helper on declared Go sources "
                "and check a declared summary manifest against the fresh "
                "report."
            ),
        )
        go_summaries_check_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(go_summaries_check_main(args))
    elif command == "go-summaries-reuse":
        import argparse
        from agent.go_summaries import (
            build_reuse_parser as go_summaries_reuse_build_parser,
            main_reuse as go_summaries_reuse_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent go-summaries-reuse",
            description=(
                "Run a provisioned go-types helper on declared Go sources "
                "and emit a manifest reusing a declared manifest's "
                "unchanged summaries."
            ),
        )
        go_summaries_reuse_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(go_summaries_reuse_main(args))
    elif command == "go-summaries-accept":
        import argparse
        from agent.go_summaries import (
            build_accept_parser as go_summaries_accept_build_parser,
            main_accept as go_summaries_accept_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent go-summaries-accept",
            description=(
                "Run a provisioned go-types helper on declared Go sources "
                "and accept one function's declared summary under the "
                "strict whole-context gate."
            ),
        )
        go_summaries_accept_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(go_summaries_accept_main(args))
    elif command == "summaries-plan":
        import argparse
        from agent.summaries_adapters import (
            build_plan_parser as summaries_plan_build_parser,
            main_plan as summaries_plan_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent summaries-plan",
            description=(
                "Plan the summary-derivation route for a declared "
                "profile through the C11 probe boundary and print the "
                "plan JSON."
            ),
        )
        summaries_plan_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(summaries_plan_main(args))
    elif command == "go-summaries-attempt":
        import argparse
        from agent.go_summaries import (
            build_attempt_parser as go_summaries_attempt_build_parser,
            main_attempt as go_summaries_attempt_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent go-summaries-attempt",
            description=(
                "Run the go-summaries produce route as one declared "
                "attempt and emit the reconciled lineage descriptors."
            ),
        )
        go_summaries_attempt_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(go_summaries_attempt_main(args))
    elif command == "go-summaries-reuse-attempt":
        import argparse
        from agent.go_summaries import (
            build_reuse_attempt_parser
            as go_summaries_reuse_attempt_build_parser,
            main_reuse_attempt as go_summaries_reuse_attempt_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent go-summaries-reuse-attempt",
            description=(
                "Run the go-summaries-reuse route as one declared "
                "attempt and emit the reconciled lineage descriptors."
            ),
        )
        go_summaries_reuse_attempt_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(go_summaries_reuse_attempt_main(args))
    elif command == "evidence-check":
        import argparse
        from agent.evidence_check_route import (
            build_check_parser as evidence_check_build_parser,
            main_check as evidence_check_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent evidence-check",
            description=(
                "Run a declared Core Evidence representation check on "
                "a saved record as one attempt and emit the reconciled "
                "lineage plus the declared representation outcome."
            ),
        )
        evidence_check_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(evidence_check_main(args))
    elif command == "evidence-check-list":
        import argparse
        from agent.evidence_check_list import (
            build_check_list_parser as evidence_check_list_build_parser,
            main_check_list as evidence_check_list_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent evidence-check-list",
            description=(
                "Run a declared Core Evidence list-envelope "
                "representation check as one attempt and emit the "
                "reconciled lineage plus the declared representation "
                "outcome."
            ),
        )
        evidence_check_list_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(evidence_check_list_main(args))
    elif command == "evidence-check-accept":
        import argparse
        from agent.evidence_check import (
            build_accept_parser as evidence_accept_build_parser,
            main_accept as evidence_accept_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent evidence-check-accept",
            description=(
                "Evaluate a declared evidence-check record against a "
                "restored attempt-sequence snapshot and emit the "
                "representation-level acceptance descriptor."
            ),
        )
        evidence_accept_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(evidence_accept_main(args))
    elif command == "evidence-check-consistency":
        import argparse
        from agent.evidence_check_consistency import (
            build_check_consistency_parser as consistency_build_parser,
            main_check_consistency as consistency_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent evidence-check-consistency",
            description=(
                "Run a declared Core Evidence list cross-record "
                "consistency check as one attempt and emit the "
                "reconciled lineage plus the declared consistency "
                "outcome."
            ),
        )
        consistency_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(consistency_main(args))
    elif command == "evidence-acceptance-eval":
        import argparse
        from agent.evidence_acceptance_eval import (
            build_eval_parser as acceptance_eval_build_parser,
            main_eval as acceptance_eval_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent evidence-acceptance-eval",
            description=(
                "Evaluate a declared Core acceptance descriptor and "
                "emit the representation-level acceptance evaluation."
            ),
        )
        acceptance_eval_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(acceptance_eval_main(args))
    elif command == "signature-eval":
        import argparse
        from agent.signature_eval import (
            build_eval_parser as signature_eval_build_parser,
            main_eval as signature_eval_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent signature-eval",
            description=(
                "Evaluate a declared producer-signature envelope and "
                "emit the representation-level evaluation."
            ),
        )
        signature_eval_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(signature_eval_main(args))
    elif command == "signature-verify":
        import argparse
        from agent.signature_verify import (
            build_verify_parser as signature_verify_build_parser,
            main_verify as signature_verify_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent signature-verify",
            description=(
                "Verify a declared producer-signature envelope's "
                "ed25519 signature under a declared public key and "
                "emit the verification descriptor."
            ),
        )
        signature_verify_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(signature_verify_main(args))
    elif command == "recovery-eval":
        import argparse
        from agent.recovery_eval import (
            build_eval_parser as recovery_eval_build_parser,
            main_eval as recovery_eval_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent recovery-eval",
            description=(
                "Fold a declared record's checks_not_performed over "
                "supporting evaluation documents and emit the "
                "recovery descriptor."
            ),
        )
        recovery_eval_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(recovery_eval_main(args))
    elif command == "freshness-eval":
        import argparse
        from agent.freshness_eval import (
            build_eval_parser as freshness_eval_build_parser,
            main_eval as freshness_eval_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent freshness-eval",
            description=(
                "Evaluate a declared record's produced_at freshness "
                "claim against a declared reference time and emit "
                "the evaluation descriptor."
            ),
        )
        freshness_eval_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(freshness_eval_main(args))
    elif command == "binding-eval":
        import argparse
        from agent.binding_eval import (
            build_eval_parser as binding_eval_build_parser,
            main_eval as binding_eval_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent binding-eval",
            description=(
                "Pin a declared subject-bearing document to record "
                "bytes and emit the binding descriptor."
            ),
        )
        binding_eval_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(binding_eval_main(args))
    elif command == "evidence-identity-check":
        import argparse
        from agent.evidence_identity import (
            build_identity_parser as evidence_identity_build_parser,
            main_identity as evidence_identity_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent evidence-identity-check",
            description=(
                "Check a declared evidence record's source binding "
                "against a declared source file and emit the "
                "representation-level file-identity descriptor."
            ),
        )
        evidence_identity_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(evidence_identity_main(args))
    elif command == "evidence-producer-check":
        import argparse
        from agent.evidence_producer import (
            build_producer_parser as evidence_producer_build_parser,
            main_producer as evidence_producer_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent evidence-producer-check",
            description=(
                "Check a declared evidence record's provenance "
                "against declared producer expectations and emit "
                "the representation-level producer-identity "
                "descriptor."
            ),
        )
        evidence_producer_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(evidence_producer_main(args))
    elif command == "evidence-compare":
        import argparse
        from agent.evidence_compare import (
            build_compare_parser as evidence_compare_build_parser,
            main_compare as evidence_compare_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent evidence-compare",
            description=(
                "Compare two declared evidence records' bound subject "
                "and specification claims and emit the "
                "representation-level comparison descriptor."
            ),
        )
        evidence_compare_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(evidence_compare_main(args))
    elif command == "verify-attempt":
        import argparse
        from agent.verify_attempt import (
            build_attempt_parser as verify_attempt_build_parser,
            main_attempt as verify_attempt_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent verify-attempt",
            description=(
                "Run a declared Core source-evidence production as one "
                "attempt and emit the reconciled lineage, the live "
                "representation check record and its acceptance."
            ),
        )
        verify_attempt_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(verify_attempt_main(args))
    elif command == "verify-recheck":
        import argparse
        from agent.verify_recheck import (
            build_recheck_parser as verify_recheck_build_parser,
            main_recheck as verify_recheck_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent verify-recheck",
            description=(
                "Run a declared Core source-evidence recheck as one "
                "attempt and emit the reconciled lineage plus the "
                "declared recheck outcome."
            ),
        )
        verify_recheck_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(verify_recheck_main(args))
    elif command == "verify-accept":
        import argparse
        from agent.verify_accept import (
            build_accept_parser as verify_accept_build_parser,
            main_accept as verify_accept_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent verify-accept",
            description=(
                "Run a declared Core source-evidence acceptance "
                "evaluation as one attempt and emit the reconciled "
                "lineage plus the declared acceptance outcome."
            ),
        )
        verify_accept_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(verify_accept_main(args))
    elif command == "verify-schedule":
        import argparse
        from agent.verify_schedule import (
            build_schedule_parser as verify_schedule_build_parser,
            main_schedule as verify_schedule_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent verify-schedule",
            description=(
                "Run the declared plan/dispatch/observe/fallback schedule "
                "over declared adapter manifests and emit "
                "mumei.attempt-schedule/v1."
            ),
        )
        verify_schedule_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(verify_schedule_main(args))
    elif command == "native-recheck":
        import argparse
        from agent.native_recheck import (
            build_recheck_parser as native_recheck_build_parser,
            main_recheck as native_recheck_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-recheck",
            description=(
                "Run a declared Core native consumer recheck as one "
                "attempt and emit the reconciled lineage plus the "
                "declared recheck outcome."
            ),
        )
        native_recheck_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_recheck_main(args))
    elif command == "native-attempt":
        import argparse
        from agent.native_attempt import (
            build_attempt_parser as native_attempt_build_parser,
            main_attempt as native_attempt_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-attempt",
            description=(
                "Run a declared Core native bundle production as one "
                "attempt and emit the reconciled lineage plus the "
                "declared Build ID."
            ),
        )
        native_attempt_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_attempt_main(args))
    elif command == "native-accept":
        import argparse
        from agent.native_accept import (
            build_accept_parser as native_accept_build_parser,
            main_accept as native_accept_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-accept",
            description=(
                "Run a declared Core native artifact acceptance as one "
                "attempt and emit the reconciled lineage plus the "
                "declared acceptance outcome."
            ),
        )
        native_accept_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_accept_main(args))
    elif command == "native-artifact-recheck":
        import argparse
        from agent.native_artifact_recheck import (
            build_artifact_recheck_parser as native_arc_build_parser,
            main_artifact_recheck as native_arc_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-artifact-recheck",
            description=(
                "Run a declared Core native artifact recheck as one "
                "attempt and emit the reconciled lineage plus the "
                "declared recheck outcome."
            ),
        )
        native_arc_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_arc_main(args))
    elif command == "native-exit-status-recheck":
        import argparse
        from agent.native_exit_status_recheck import (
            build_exit_status_recheck_parser as native_esr_build_parser,
            main_exit_status_recheck as native_esr_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-exit-status-recheck",
            description=(
                "Run a declared Core native exit-status recheck as one "
                "attempt and emit the reconciled lineage plus the "
                "declared recheck outcome."
            ),
        )
        native_esr_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_esr_main(args))
    elif command == "native-exit-status-accept":
        import argparse
        from agent.native_exit_status_accept import (
            build_exit_status_accept_parser as native_esa_build_parser,
            main_exit_status_accept as native_esa_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-exit-status-accept",
            description=(
                "Run a declared Core native exit-status acceptance as "
                "one attempt and emit the reconciled lineage plus the "
                "declared acceptance outcome."
            ),
        )
        native_esa_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_esa_main(args))
    elif command == "native-stdout-recheck":
        import argparse
        from agent.native_stdout_recheck import (
            build_stdout_recheck_parser as native_osr_build_parser,
            main_stdout_recheck as native_osr_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-stdout-recheck",
            description=(
                "Run a declared Core native stdout recheck as one "
                "attempt and emit the reconciled lineage plus the "
                "declared recheck outcome."
            ),
        )
        native_osr_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_osr_main(args))
    elif command == "native-stdout-accept":
        import argparse
        from agent.native_stdout_accept import (
            build_stdout_accept_parser as native_osa_build_parser,
            main_stdout_accept as native_osa_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-stdout-accept",
            description=(
                "Run a declared Core native stdout acceptance as "
                "one attempt and emit the reconciled lineage plus the "
                "declared acceptance outcome."
            ),
        )
        native_osa_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_osa_main(args))
    elif command == "native-stderr-recheck":
        import argparse
        from agent.native_stderr_recheck import (
            build_stderr_recheck_parser as native_oxr_build_parser,
            main_stderr_recheck as native_oxr_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-stderr-recheck",
            description=(
                "Run a declared Core native stderr recheck as one "
                "attempt and emit the reconciled lineage plus the "
                "declared recheck outcome."
            ),
        )
        native_oxr_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_oxr_main(args))
    elif command == "native-stderr-accept":
        import argparse
        from agent.native_stderr_accept import (
            build_stderr_accept_parser as native_oxa_build_parser,
            main_stderr_accept as native_oxa_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-stderr-accept",
            description=(
                "Run a declared Core native stderr acceptance as "
                "one attempt and emit the reconciled lineage plus the "
                "declared acceptance outcome."
            ),
        )
        native_oxa_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_oxa_main(args))
    elif command == "native-check":
        import argparse
        from agent.native_check import (
            build_check_parser as native_check_build_parser,
            main_check as native_check_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-check",
            description=(
                "Run a declared Core native bundle identity check as "
                "one attempt and emit the reconciled lineage plus the "
                "declared check outcome."
            ),
        )
        native_check_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_check_main(args))
    elif command == "native-source-recheck":
        import argparse
        from agent.native_source_recheck import (
            build_source_recheck_parser as native_source_recheck_build_parser,
            main_source_recheck as native_source_recheck_main,
        )
        parser = argparse.ArgumentParser(
            prog="python -m agent native-source-recheck",
            description=(
                "Run a declared Core native bundle source recheck as "
                "one attempt and emit the reconciled lineage plus the "
                "declared source recheck outcome."
            ),
        )
        native_source_recheck_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_source_recheck_main(args))
    elif command == "native-evidence-recheck":
        import argparse
        from agent.native_evidence_recheck import (
            build_evidence_recheck_parser as native_erc_build_parser,
            main_evidence_recheck as native_erc_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-evidence-recheck",
            description=(
                "Replay a saved native consumer Evidence envelope "
                "against a fresh pinned recheck as one declared "
                "attempt and emit the reconciled lineage plus the "
                "declared outcome."
            ),
        )
        native_erc_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_erc_main(args))
    elif command == "native-evidence-accept":
        import argparse
        from agent.native_evidence_accept import (
            build_evidence_accept_parser as native_eac_build_parser,
            main_evidence_accept as native_eac_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent native-evidence-accept",
            description=(
                "Run a declared Core native saved-Evidence acceptance "
                "as one attempt and emit the reconciled lineage plus "
                "the declared acceptance outcome."
            ),
        )
        native_eac_build_parser(parser)
        args = parser.parse_args(argv[1:])
        raise SystemExit(native_eac_main(args))
    elif command == "rust-summaries":
        import argparse
        from agent.rust_interprocedural import (
            build_parser as rust_build_parser,
            main as rust_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent rust-summaries",
            description=(
                "Emit opt-in Rust interprocedural dependency "
                "summaries as JSON — a conservative report, not a "
                "proof or verdict."
            ),
        )
        rust_build_parser(parser)
        args = parser.parse_args(argv[1:])
        rust_main(args)
    elif command == "rust-summaries-accept":
        import argparse
        from agent.rust_interprocedural import (
            build_accept_parser as rust_accept_build_parser,
            main_accept as rust_accept_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent rust-summaries-accept",
            description=(
                "Accept one function's declared Rust summary "
                "under the strict whole-context gate."
            ),
        )
        rust_accept_build_parser(parser)
        args = parser.parse_args(argv[1:])
        rust_accept_main(args)
    elif command == "rust-summaries-check":
        import argparse
        from agent.rust_interprocedural import (
            build_check_parser as rust_check_build_parser,
            main_check as rust_check_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent rust-summaries-check",
            description=(
                "Check a declared Rust summary manifest "
                "against the fresh derivation."
            ),
        )
        rust_check_build_parser(parser)
        args = parser.parse_args(argv[1:])
        rust_check_main(args)
    elif command == "rust-summaries-reuse":
        import argparse
        from agent.rust_interprocedural import (
            build_reuse_parser as rust_reuse_build_parser,
            main_reuse as rust_reuse_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent rust-summaries-reuse",
            description=(
                "Emit a manifest reusing a declared manifest's "
                "unchanged Rust summaries."
            ),
        )
        rust_reuse_build_parser(parser)
        args = parser.parse_args(argv[1:])
        rust_reuse_main(args)
    elif command == "rust-summaries-attempt":
        import argparse
        from agent.rust_interprocedural import (
            build_attempt_parser as rust_attempt_build_parser,
            main_attempt as rust_attempt_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent rust-summaries-attempt",
            description=(
                "Run the rust-summaries produce route as one declared "
                "attempt and emit the reconciled lineage descriptors."
            ),
        )
        rust_attempt_build_parser(parser)
        args = parser.parse_args(argv[1:])
        rust_attempt_main(args)

    elif command == "rust-summaries-reuse-attempt":
        import argparse
        from agent.rust_interprocedural import (
            build_reuse_attempt_parser as rust_build_parser,
            main_reuse_attempt as rust_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent rust-summaries-reuse-attempt",
            description=(
                "Run the rust-summaries-reuse route as one declared "
                "attempt and emit the reconciled lineage descriptors."
            ),
        )
        rust_build_parser(parser)
        args = parser.parse_args(argv[1:])
        rust_main(args)
    elif command == "ts-summaries":
        import argparse
        from agent.ts_interprocedural import (
            build_parser as ts_build_parser,
            main as ts_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent ts-summaries",
            description="Emit opt-in TypeScript interprocedural dependency summaries as JSON — a conservative report, not a proof or verdict.",
        )
        ts_build_parser(parser)
        args = parser.parse_args(argv[1:])
        ts_main(args)
    elif command == "ts-summaries-accept":
        import argparse
        from agent.ts_interprocedural import (
            build_accept_parser as ts_build_parser,
            main_accept as ts_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent ts-summaries-accept",
            description="Accept one function's declared TypeScript summary under the strict whole-context gate.",
        )
        ts_build_parser(parser)
        args = parser.parse_args(argv[1:])
        ts_main(args)
    elif command == "ts-summaries-check":
        import argparse
        from agent.ts_interprocedural import (
            build_check_parser as ts_build_parser,
            main_check as ts_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent ts-summaries-check",
            description="Check a declared TypeScript summary manifest against the fresh derivation.",
        )
        ts_build_parser(parser)
        args = parser.parse_args(argv[1:])
        ts_main(args)
    elif command == "ts-summaries-reuse":
        import argparse
        from agent.ts_interprocedural import (
            build_reuse_parser as ts_build_parser,
            main_reuse as ts_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent ts-summaries-reuse",
            description="Emit a manifest reusing a declared manifest's unchanged TypeScript summaries.",
        )
        ts_build_parser(parser)
        args = parser.parse_args(argv[1:])
        ts_main(args)
    elif command == "ts-summaries-attempt":
        import argparse
        from agent.ts_interprocedural import (
            build_attempt_parser as ts_build_parser,
            main_attempt as ts_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent ts-summaries-attempt",
            description="Run the ts-summaries produce route as one declared attempt and emit the reconciled lineage descriptors.",
        )
        ts_build_parser(parser)
        args = parser.parse_args(argv[1:])
        ts_main(args)

    elif command == "ts-summaries-reuse-attempt":
        import argparse
        from agent.ts_interprocedural import (
            build_reuse_attempt_parser as ts_build_parser,
            main_reuse_attempt as ts_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent ts-summaries-reuse-attempt",
            description=(
                "Run the ts-summaries-reuse route as one declared "
                "attempt and emit the reconciled lineage descriptors."
            ),
        )
        ts_build_parser(parser)
        args = parser.parse_args(argv[1:])
        ts_main(args)
    elif command == "sol-summaries":
        import argparse
        from agent.sol_interprocedural import (
            build_parser as sol_build_parser,
            main as sol_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent sol-summaries",
            description="Emit opt-in Solidity interprocedural dependency summaries as JSON — a conservative report, not a proof or verdict.",
        )
        sol_build_parser(parser)
        args = parser.parse_args(argv[1:])
        sol_main(args)
    elif command == "sol-summaries-accept":
        import argparse
        from agent.sol_interprocedural import (
            build_accept_parser as sol_build_parser,
            main_accept as sol_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent sol-summaries-accept",
            description="Accept one function's declared Solidity summary under the strict whole-context gate.",
        )
        sol_build_parser(parser)
        args = parser.parse_args(argv[1:])
        sol_main(args)
    elif command == "sol-summaries-check":
        import argparse
        from agent.sol_interprocedural import (
            build_check_parser as sol_build_parser,
            main_check as sol_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent sol-summaries-check",
            description="Check a declared Solidity summary manifest against the fresh derivation.",
        )
        sol_build_parser(parser)
        args = parser.parse_args(argv[1:])
        sol_main(args)
    elif command == "sol-summaries-reuse":
        import argparse
        from agent.sol_interprocedural import (
            build_reuse_parser as sol_build_parser,
            main_reuse as sol_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent sol-summaries-reuse",
            description="Emit a manifest reusing a declared manifest's unchanged Solidity summaries.",
        )
        sol_build_parser(parser)
        args = parser.parse_args(argv[1:])
        sol_main(args)
    elif command == "sol-summaries-attempt":
        import argparse
        from agent.sol_interprocedural import (
            build_attempt_parser as sol_build_parser,
            main_attempt as sol_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent sol-summaries-attempt",
            description="Run the sol-summaries produce route as one declared attempt and emit the reconciled lineage descriptors.",
        )
        sol_build_parser(parser)
        args = parser.parse_args(argv[1:])
        sol_main(args)

    elif command == "sol-summaries-reuse-attempt":
        import argparse
        from agent.sol_interprocedural import (
            build_reuse_attempt_parser as sol_build_parser,
            main_reuse_attempt as sol_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent sol-summaries-reuse-attempt",
            description=(
                "Run the sol-summaries-reuse route as one declared "
                "attempt and emit the reconciled lineage descriptors."
            ),
        )
        sol_build_parser(parser)
        args = parser.parse_args(argv[1:])
        sol_main(args)
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
        # sees file or directory targets (e.g. ['agent', 'path/to/std', ...]).
        sys.argv = [sys.argv[0]] + argv[1:]
        heal_main()
    else:
        # Backward compatibility: no subcommand means heal mode
        # (e.g. `python -m agent examples/sword_test.mm`)
        from agent.self_healing import main as heal_main
        heal_main()

if __name__ == "__main__":
    main()
