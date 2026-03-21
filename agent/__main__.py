"""Allow running as `python -m agent` with subcommands."""
import sys

_SUBCOMMANDS = {"heal", "generate"}


def main() -> None:
    """Route to heal or generate subcommand."""
    # Determine the subcommand by inspecting the first positional arg
    # *before* argparse runs, so that unknown positional args (e.g.
    # `python -m agent examples/sword_test.mm`) fall through to heal
    # mode instead of being rejected as invalid subcommand choices.
    argv = sys.argv[1:]
    command = argv[0] if argv and argv[0] in _SUBCOMMANDS else None

    if command == "generate":
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
