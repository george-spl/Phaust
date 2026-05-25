# Phaust roadmap

## Phaust-1 (tag: `phaust-1-regression-complete`)

- Local console agent, SQLite memory, workspace read/write with approval
- Grounded answers after `read_file` (explain mode)
- Write path: intent detection, single nudge, XML tool-call parsing, clean post-write replies
- Regression block R1–R7: **6 PASS, 1 PARTIAL** (R4 semantic search at tag time; R4 later **PASS** in Phaust-2)

## Phaust-2 (current on `experimental`)

Graduated from Phaust-1 on 2026-05-24. See [ITERATIONS.md](ITERATIONS.md).

### Architecture

| Piece | Status |
|-------|--------|
| `phaust/orchestration/` | **Done** |
| `phaust/tasks/` | **Done** |
| `phaust/memory/retrieval.py` | **Done** |
| `turn_loop.py` + `tool_executor.py` | **Done** — chat loop extracted from `agent.py` |
| `agent.py` slim-down | **Done** — session + registration only (~120 lines) |
| Tool recovery nudge | **Done** — one retry hint per turn on recoverable errors |
| Synthesis model profile | **Done** — optional `[llm.synthesis]` in `phaust.toml` |

### Features

| Area | Status |
|------|--------|
| **Config** | Done — `phaust.toml` iteration 2 |
| **Rules** | Done — `AGENTS.md` identity + iteration history |
| **Shell** | Done |
| **Tasks** | Done — multi-step mode, checkpoints, REPL commands |
| **Memory** | Done — hybrid retrieval, full search_semantic output |
| **Models** | Partial — `[llm.synthesis]` profile; per-task profiles still planned |
| **Packaging** | **Done** — `pip install -e .` and `phaust` CLI |
| **Recap** | **Done** — `phaust recap` (tasks, facts, episodes, live context) |
| **Resume / ask** | **Done** — `phaust resume`, `phaust ask`, `/resume` `/recap` in chat |
| **Topic memory** | **Done** — auto tags on `memorize`, boost `search_semantic` by topic |
| **Workspace rules** | **Done** — `AGENTS.md` layout (user docs in `docs/` / `notes/`, never `Memory/`) |

### Memory UX (v2.1 polish)

| Area | Status |
|------|--------|
| Prose memory answers | **Done** — no raw tool dumps for conversational recall |
| `continue_from` + session pointer | **Done** — `session_state.json` biases “last time” toward latest topic |
| Recall nudge tuning | **Done** — no nudge when pointer exists; feedback lines not treated as lookups |
| Intent fixes | **Done** — “make you smarter” ≠ write; narrative “last session” ≠ stress recall |

### Next (v2.2)

- MCP plugin slot in `phaust.toml`
- Parallel tool reads in one turn
- Per-task / chat model profiles beyond `[llm.synthesis]`
- Memory CLI (`phaust memory search`, …)

Contributions welcome on branch `experimental`.
