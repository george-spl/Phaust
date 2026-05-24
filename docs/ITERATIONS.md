# Phaust iteration history

Canonical record of Phaust versions. **AGENTS.md** summarizes this for every session.

## Phaust-1

**Tag:** `phaust-1-regression-complete` (2026-05-24)

- Local console agent: SQLite memory, workspace tools, write/shell approval gates
- Stress-tested blocks A–L; regression R1–R7 ended **6 PASS, 1 PARTIAL** (R4 semantic search)
- Architecture: monolithic `agent.py` with inline regex and nudge logic
- Known v1 limits: logging self-assessment label scramble; model-dependent nudge soup

**Graduated** when regression was green and Phaust-2 architecture work began.

## Phaust-2 (current)

**Branch:** `experimental` · **Config:** `phaust.toml` → `iteration = 2`, `name = "Phaust-2"`

Built on Phaust-1's safety model and tool set. New structure:

| Layer | Purpose |
|-------|---------|
| `phaust/orchestration/` | Intent → directives → policy → outcomes (no new regex in agent) |
| `phaust/tasks/` | Multi-step task mode, JSON checkpoints in `Memory/tasks/` |
| `phaust/memory/retrieval.py` | Hybrid semantic search (filename boost, query expansion) |

Same George, same workspace, same approval gates — cleaner internals and task/retrieval features.

**Install:** `pip install -e .` from the repo, then run `phaust` in any directory with `phaust.toml`.

## Future

See [ROADMAP.md](ROADMAP.md) for packaging, model profiles, and memory review UI.
