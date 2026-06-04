# Phaust-2

**P**ractical **H**elper **A**utomated **U**tility **S**ystem — Iteration 2

Successor to **Phaust-1** ([tag `phaust-1-regression-complete`](docs/ITERATIONS.md)). Same local agent with a cleaner architecture — orchestration layer, task mode, hybrid memory, and a `phaust` CLI.

A private AI assistant in your terminal: local LLM via [LM Studio](https://lmstudio.ai) (OpenAI-compatible API), SQLite memory, workspace tools, and approval gates for writes and shell.

**Repository:** GitHub remote is [george-spl/Phaust-1](https://github.com/george-spl/Phaust-1); active development is on branch **`experimental`**.

## Requirements

- Python 3.11+
- LM Studio (or compatible server) at `http://127.0.0.1:1234`
- **Two models loaded** for full memory quality:
  - **Chat:** `qwen/qwen3.5-9b` (tools + conversation)
  - **Embeddings:** `text-embedding-nomic-embed-text-v1.5` (semantic search; must match `[memory].embedding_model` in `phaust.toml`)

## Setup

### Install

```powershell
cd D:\github\Phaust-2
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

### LM Studio

1. Download **Qwen3.5-9B** (Q4_K_M recommended on 12GB VRAM) and **nomic embed** from Discover.
2. Load **both** models; start the local server (port **1234**).
3. Set context **16384** on the chat model if VRAM is tight (**32768** only if comfortable).
4. Turn **thinking off** for Qwen (Custom fields / template — see [docs/STRESS_TESTS.md](docs/STRESS_TESTS.md)).
5. Confirm API ids:

```powershell
curl http://127.0.0.1:1234/v1/models
```

Match ids to `phaust.toml` (`[llm].model` and `[memory].embedding_model`).

### Run

From the directory that contains `phaust.toml`:

```powershell
phaust              # interactive chat
phaust recap        # tasks, facts, episodes — no LLM
phaust resume       # recap + session pointer
phaust ask "…"      # one message, then exit
phaust -C D:\path\to\other\project
```

`python main.py` works in this repo (workspace = repo root). Type `exit` or `quit` to archive the session.

## What it does

| Layer | Role |
|-------|------|
| **Context** | Recent chat (50 messages), session variables, live context |
| **Long-term** | Facts (`remember` / `recall` / `forget`) — keys like `user_name`, `user_job` |
| **Semantic** | Episode summaries + hybrid `search_semantic` (embeddings via nomic when configured) |
| **Tasks** | Multi-step checkpoints (`task start Title :: step1 :: step2`) |

Older messages compact into episodes (+ optional extracted facts) on overflow and on `exit`.

**Explain vs edit:** “What does this file do?” → read + synthesis (`turn_runner.py`). “Edit / write” → tool path with diff approval, no synthesis.

**Orchestration:** `phaust/orchestration/` classifies each turn (intent, nudges, outcomes) — not ad-hoc logic in `agent.py`.

**Resume:** `phaust resume` and `Memory/session_state.json` bias “what were we doing last time?” toward the latest topic (prose answers, not raw episode dumps).

## Tools

**Workspace:** `read_file`, `list_directory`, `list_files`, `grep`, `create_file`, `edit_file`, `write_file`, `delete_file`, `run_command` (allowlisted).

**Writes / shell:** Preview + `y/N` at the terminal. Protected: `Memory/`, `.venv/`, `.git/`, etc.

**Memory:** `remember`, `recall`, `forget`, `list_memories`, `memorize`, `search_semantic`, `recall_episode`, `list_episodes`, `forget_semantic`, `set_session`, `get_session`.

**Task mode (REPL):** `task help`, `task start`, `task next`, `task pause` / `resume`, `task done` — checkpoints under `Memory/tasks/`.

**Private session:** `remember nothing this session` — no saves; transcript discarded on exit.

## Project layout

```
main.py              Legacy entry (repo root as workspace)
pyproject.toml       pip install -e . → phaust CLI
phaust.toml          Runtime settings (models, memory, shell)
AGENTS.md            Rules loaded every session
phaust/
  cli.py repl.py     CLI and interactive session
  turn_loop.py       Chat loop (LLM, tools, nudges)
  turn_runner.py     Synthesis + enable_thinking=false on API
  orchestration/     Intent, policy, nudges, outcomes
  memory/            SQLite, compaction, hybrid retrieval
  tasks/             Multi-step task mode
docs/
  ARCHITECTURE.md    Layers and design rules
  ITERATIONS.md      v1 vs v2
  ROADMAP.md         Status and plans
  STRESS_TESTS.md    Manual QA matrix (blocks A–L)
Memory/              phaust.db, tasks/, session_state.json (gitignored)
test_logging.txt     Manual stress log (operator + Phaust notes)
tests/               Lightweight import checks (optional, untracked in some clones)
```

## Configuration (`phaust.toml`)

Override path with env `PHAUST_CONFIG`.

| Section | Purpose |
|---------|---------|
| `[phaust]` | `name`, `iteration` |
| `[llm]` | `model`, `base_url`, `temperature`, `max_tokens` (default **2048** for chat) |
| `[llm.synthesis]` | Optional second pass for explain-mode (defaults to `[llm]`) |
| `[memory]` | `embedding_model`, `max_messages`, `compact_batch`, hybrid retrieval knobs |
| `[agent]` | `agents_md`, tool round limits, write approval |
| `[tasks]` | Task mode storage |
| `[shell]` | Allowlist + approval |

Example defaults in this repo:

```toml
[llm]
model = "qwen/qwen3.5-9b"
max_tokens = 2048

[memory]
embedding_model = "text-embedding-nomic-embed-text-v1.5"
```

**Project rules:** [`AGENTS.md`](AGENTS.md).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `400` / “No user query found” | Empty `You:` prompt — restart; Phaust may auto-repair context |
| Semantic search weak / no hits | Check nomic loaded; verify `embedding_model` id; see LM Studio logs for `/embeddings` |
| Long rambling replies | Lower `max_tokens`; disable thinking; use Q4 quant |
| Edit without `read_file` | Tool error + nudge — read file, retry |
| “Last time” = old stress tests | `phaust resume`; chat + `exit` to refresh session pointer |
| Wrong venv | Recreate `.venv`, `pip install -e .` |

## Inspecting memory

```powershell
phaust recap
phaust resume
sqlite3 Memory\phaust.db
```

```sql
SELECT key, value FROM facts;
SELECT substr(text, 1, 100), created_at FROM episodes ORDER BY created_at DESC LIMIT 5;
```

## Testing

**Manual (primary):** Follow [`docs/STRESS_TESTS.md`](docs/STRESS_TESTS.md) in `phaust`; record in `test_logging.txt`.

**Quick import checks** (optional `tests/` modules):

```powershell
python -c "import tests.test_orchestration, tests.test_turn_runner, tests.test_recap, tests.test_tasks"
```

No pytest harness in-tree; stress QA is operator-driven.

## What's next

[docs/ROADMAP.md](docs/ROADMAP.md) — MCP, parallel reads, memory CLI, model profiles.

## License

Personal project — use and modify as you like.
