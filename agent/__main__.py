"""Allow running as `python -m agent` with subcommands."""
import argparse
import sys


def main() -> None:
    """Route to heal or generate subcommand."""
    parser = argparse.ArgumentParser(
        prog="python -m agent",
        description="Mumei Agent: AI-driven autonomous fix and generation loop",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- heal subcommand ---
    heal_parser = subparsers.add_parser(
        "heal",
        help="Self-healing loop: fix verification failures",
        description="Mumei Self-Healing Loop: AI-driven autonomous fix loop",
    )
    heal_parser.add_argument(
        "source_file",
        nargs="?",
        default="examples/sword_test.mm",
        help="Path to the .mm source file to heal (default: examples/sword_test.mm)",
    )
    heal_parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Maximum number of fix attempts (default: from config or 5)",
    )
    heal_parser.add_argument(
        "--strategy",
        choices=["single", "multi-stage"],
        default=None,
        help="Fix strategy: 'single' (one-shot) or 'multi-stage' (diagnose->fix->validate). "
             "Default: from AGENT_STRATEGY env var or 'single'.",
    )
    # --- generate subcommand ---
    from agent.generate import build_parser as build_generate_parser
    build_generate_parser(subparsers)

    args = parser.parse_args()

    if args.command == "generate":
        from agent.generate import main as generate_main
        generate_main(args)
    elif args.command == "heal":
        from agent.self_healing import main as heal_main
        # Strip the 'heal' subcommand from sys.argv so self_healing
        # sees only its own arguments (e.g. ['agent', 'file.mm'])
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        heal_main()
    else:
        # Backward compatibility: no subcommand means heal mode
        from agent.self_healing import main as heal_main
        heal_main()


main()
