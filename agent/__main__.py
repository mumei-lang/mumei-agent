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
    "self-correct",
    "mcp-server",
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
    elif command == "self-correct":
        import argparse
        from agent.strategies.self_correction_strategy import (
            build_parser as self_correct_build_parser,
            main as self_correct_main,
        )

        parser = argparse.ArgumentParser(
            prog="python -m agent self-correct",
            description="Run the P9-F self-correction protocol.",
        )
        self_correct_build_parser(parser)
        args = parser.parse_args(argv[1:])
        self_correct_main(args)
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
