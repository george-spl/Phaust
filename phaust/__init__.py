"""Phaust-2 — local agent package."""

from phaust.agent import Agent
from phaust.repl import run
from phaust.app import build_agent

__version__ = "2.0.0"

__all__ = ["Agent", "run", "build_agent", "__version__"]
