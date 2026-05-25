"""Phaust command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from phaust import __version__
from phaust.repl import run
from phaust.app import build_agent
from phaust.recap import build_recap


def main(default_workspace: Path | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="phaust",
        description="Phaust - local AI agent with tools, memory, and approval gates.",
    )
    parser.add_argument(
        "-C",
        "--workspace",
        type=Path,
        default=None,
        help="Project root containing phaust.toml (default: current directory)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"phaust {__version__}",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("chat", help="Interactive agent session (default)")
    sub.add_parser("recap", help="Summarize tasks, memory, and recent episodes")

    args = parser.parse_args()
    root = (args.workspace or default_workspace or Path.cwd()).resolve()

    command = args.command or "chat"
    if command == "recap":
        print(build_recap(root))
        return
    if command == "chat":
        run(build_agent(root))
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
