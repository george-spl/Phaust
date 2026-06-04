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

Built on Phaust-1's safety model and tool set:

| Layer | Purpose |
|-------|---------|
| `phaust/orchestration/` | Intent → directives → policy → outcomes (no new regex in `agent.py`) |
| `phaust/tasks/` | Multi-step task mode, JSON checkpoints in `Memory/tasks/` |
| `phaust/memory/retrieval.py` | Hybrid semantic search (filename boost, query expansion) |
| `phaust/turn_loop.py` | Chat turn loop extracted from `agent.py` |
| CLI | `phaust`, `phaust recap`, `phaust resume`, `phaust ask` |

**v2.1 (operator layer):** Session pointer (`session_state.json`), topic-tagged `memorize`, workspace layout rules, prose-first “last time” answers, tuned recall nudges.

**v2.1.1 (config):** `[memory].embedding_model` wired to LM Studio embeddings API (e.g. nomic); chat model stays on `[llm].model`. API requests pass `enable_thinking: false` via `turn_runner.llm_extra()`.

### Operator stack (2026-06)

Typical local setup on `experimental`:

| Role | LM Studio model id |
|------|-------------------|
| Chat + tools | `qwen/qwen3.5-9b` |
| Embeddings | `text-embedding-nomic-embed-text-v1.5` |

`phaust.toml`: `max_tokens = 2048` for chat; both models loaded while Phaust runs.

**Install:** `pip install -e .` from the repo, then `phaust` in any directory with `phaust.toml`.

## Future

See [ROADMAP.md](ROADMAP.md) for MCP, model profiles, and memory CLI.
