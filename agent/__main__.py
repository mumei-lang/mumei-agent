"""Allow running as `python -m agent` with subcommands."""
import sys

_SUBCOMMANDS = {"heal", "generate", "publish", "forge", "propose"}


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


main()
