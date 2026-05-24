"""Legacy entry point — prefer `phaust` after pip install."""

from __future__ import annotations

from pathlib import Path

from phaust.cli import main

_REPO_ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    main(default_workspace=_REPO_ROOT)
