from pathlib import Path

MEMORY_DIR = Path(__file__).resolve().parent.parent.parent / "Memory"
DB_FILE = MEMORY_DIR / "phaust.db"

# Legacy JSON (one-time import into SQLite)
CONTEXT_FILE = MEMORY_DIR / "context.json"
LONG_TERM_FILE = MEMORY_DIR / "long_term.json"
SEMANTIC_FILE = MEMORY_DIR / "semantic.json"
LEGACY_FILE = MEMORY_DIR / "memory.json"
