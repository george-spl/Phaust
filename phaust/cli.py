"""Phaust command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from phaust import __version__
from phaust.agent import run
from phaust.app import build_agent


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
    args = parser.parse_args()
    root = (args.workspace or default_workspace or Path.cwd()).resolve()
    run(build_agent(root))


if __name__ == "__main__":
    main()
