# Phaust roadmap

## Phaust-1 (tag: `phaust-1-regression-complete`)

- Local console agent, SQLite memory, workspace read/write with approval
- Grounded answers after `read_file` (explain mode)
- Stress blocks A–L; regression R1–R7: **6 PASS, 1 PARTIAL** (R4 semantic search; later **PASS** in Phaust-2)

## Phaust-2 (current on `experimental`)

Graduated from Phaust-1 on 2026-05-24. See [ITERATIONS.md](ITERATIONS.md).

### Architecture

| Piece | Status |
|-------|--------|
| `phaust/orchestration/` | **Done** |
| `phaust/tasks/` | **Done** |
| `phaust/memory/retrieval.py` | **Done** |
| `turn_loop.py` + `tool_executor.py` | **Done** |
| `agent.py` slim-down | **Done** |
| Tool recovery nudge | **Done** |
| `[llm.synthesis]` profile | **Done** (optional in `phaust.toml`) |

### Features

| Area | Status |
|------|--------|
| **Config** | Done — `phaust.toml` iteration 2 |
| **Rules** | Done — `AGENTS.md` |
| **Shell** | Done — allowlist + approval |
| **Tasks** | Done |
| **Memory** | Done — hybrid retrieval, episodes, facts |
| **Embeddings config** | **Done** — `[memory].embedding_model` → nomic (or other) in LM Studio |
| **Chat model** | Operator choice — currently **Qwen3.5-9B** in docs/`phaust.toml` |
| **Packaging** | Done — `pip install -e .`, `phaust` CLI |
| **Recap / resume / ask** | Done |
| **Topic memory** | Done |
| **Workspace rules** | Done — user files in `docs/` / `notes/`, not `Memory/` |

### Memory UX (v2.1)

| Area | Status |
|------|--------|
| Prose memory answers | **Done** |
| `continue_from` + session pointer | **Done** |
| Recall nudge tuning | **Done** |
| Intent fixes (write vs chat vs stress) | **Done** |

### Testing

| Area | Status |
|------|--------|
| Manual stress matrix | **Active** — [STRESS_TESTS.md](STRESS_TESTS.md), `test_logging.txt` |
| `tests/` import modules | Optional lightweight checks (no pytest CI) |
| Automated harness / pytest suite | Not on current baseline |

### Next (v2.2)

- MCP plugin slot in `phaust.toml`
- Parallel tool reads in one turn
- Per-task / chat model profiles beyond `[llm.synthesis]`
- Memory CLI (`phaust memory search`, …)
- Stronger chat persona in `prompts.py` (optional; rules remain in `AGENTS.md`)

Contributions welcome on branch `experimental`.
