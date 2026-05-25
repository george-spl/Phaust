"""Phaust command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from phaust import __version__
from phaust.app import build_agent
from phaust.recap import build_recap
from phaust.repl import run
from phaust.resume import build_resume
from phaust.turn_loop import run_chat_turn


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
    sub.add_parser("resume", help="Recap plus where you left off (session pointer)")
    ask_p = sub.add_parser("ask", help="Single message, then exit (no REPL)")
    ask_p.add_argument("message", nargs="+", help="Prompt for one turn")

    args = parser.parse_args()
    root = (args.workspace or default_workspace or Path.cwd()).resolve()

    command = args.command or "chat"
    if command == "recap":
        print(build_recap(root))
        return
    if command == "resume":
        print(build_resume(root))
        return
    if command == "ask":
        agent = build_agent(root)
        agent.begin_session()
        text = " ".join(args.message).strip()
        if not text:
            print("Empty message.", file=sys.stderr)
            sys.exit(1)
        reply = run_chat_turn(agent, text)
        print(reply if reply else "(empty)")
        return
    if command == "chat":
        run(build_agent(root))
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
