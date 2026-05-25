# Phaust-2

**P**ractical **H**elper **A**utomated **U**tility **S**ystem — Iteration 2

Successor to **Phaust-1** (`phaust-1-regression-complete`). Same local agent; upgraded architecture — see [docs/ITERATIONS.md](docs/ITERATIONS.md).

A local, private AI agent that runs in your terminal. It uses a local LLM (via [LM Studio](https://lmstudio.ai) or any OpenAI-compatible server), SQLite memory, and workspace tools (read, grep, and approved writes).

## Requirements

- Python 3.11+
- A local LLM server at `http://127.0.0.1:1234` (default LM Studio port)
- A chat model loaded in the server (default: `qwen/qwen3.5-9b`)

## Setup

### Option A — install the CLI (recommended)

```powershell
cd D:\github\Phaust-2
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

Start your LLM server, then from your project directory (where `phaust.toml` lives):

```powershell
phaust              # interactive chat (default)
phaust recap        # tasks, facts, episodes — no LLM session
phaust -C D:\path\to\project
```

`python main.py` still works for this repo (defaults workspace to repo root).

### Option B — run from source without installing

```powershell
pip install -r requirements.txt
python main.py
```

Type `exit` or `quit` to end the session and archive memory.

## What it does

| Layer | Role |
|-------|------|
| **Context** | Recent chat (last 50 messages), session variables, live context (time, workspace) |
| **Long-term** | Explicit facts (`remember` / `recall` / `forget`) — user profile keys like `user_name` |
| **Semantic** | Hybrid search over episode summaries (`search_semantic`, filename boost) |
| **Tasks** | Multi-step work with checkpoints (`task start Title :: step1 :: step2`) |

Older messages are auto-compacted into episodes (and durable **user** facts) so memory stays small without losing the gist.

**Explain vs edit:** For “what does this file do?”, Phaust reads the file and answers from source (synthesis pass in `turn_runner.py`). For “write / edit / add a line”, it skips synthesis and uses the write path with diff approval.

**Orchestration:** Intent, nudges, and outcomes live in `phaust/orchestration/` — not regex soup in `agent.py`. Recoverable tool errors get one retry nudge per turn (e.g. read-before-write).

## Tools

**Workspace**

- `read_file` — read a file under the project root (content is exact file text for use in `edit_file`)
- `list_directory` — list files and folders in a path (`recursive=true` for nested)
- `list_files` — glob file listing (optional `path` to scope a folder)
- `grep` — regex search in files
- `create_file` — propose creating a new file (no read first)
- `edit_file` — propose a single search/replace (unique `old_string`)
- `write_file` — propose create, overwrite, or clear (empty content)
- `delete_file` — propose removing a file from disk
- `run_command` — run an allowlisted shell command (preview + approval)

**Write safety:** Every `edit_file` / `write_file` shows a full diff first. Nothing is written until you answer `y` to `Apply this change to disk? [y/N]`.

**Shell safety:** `run_command` only runs prefixes listed in `phaust.toml` `[shell].allow`. You must answer `y` to `Run this command? [y/N]` before it executes.

Protected paths (no writes): `Memory/`, `.venv/`, `.git/`, `node_modules/`, etc.

**Memory**

- `remember`, `recall`, `forget`, `list_memories`
- `memorize`, `search_semantic`, `recall_episode`, `list_episodes`, `forget_semantic`
- `set_session`, `get_session`

**Task mode (REPL, not LLM tools)**

- `task help`, `task start Title :: step1 :: step2`, `task next`, `task pause` / `task resume`, `task done`
- Checkpoints under `Memory/tasks/` (gitignored)

**Private session:** Say e.g. `remember nothing this session` — blocks `remember` / `memorize` and discards transcript on `exit`.

## Project layout

```
main.py              Legacy entry (repo root as workspace)
pyproject.toml       pip install -e . → `phaust` CLI
phaust.toml          Runtime settings
AGENTS.md            Project rules (loaded every session)
phaust/
  cli.py             `phaust`, `phaust recap`
  app.py             build_agent(workspace)
  agent.py           Session, memory, tool registration
  turn_loop.py       Chat turn loop (LLM + tools + nudges)
  turn_runner.py     Explain-mode synthesis
  tool_executor.py   Write/shell approval execution
  prompt_context.py  System prompt assembly
  repl.py            Interactive session loop
  turn_runner.py     Synthesis pass, API message sanitization
  reply.py           User-facing reply cleanup
  recap.py           `phaust recap` snapshot
  orchestration/     Intent, policy, nudges, outcomes
  tasks/             Multi-step task mode
  memory/            SQLite, compaction, hybrid retrieval
docs/
  ARCHITECTURE.md    Layer diagram and design rules
  ROADMAP.md         Phaust-2 status and plans
  ITERATIONS.md      v1 vs v2 history
Memory/
  phaust.db          Runtime (gitignored)
```

## Configuration

Edit **`phaust.toml`** in the project root. Override path with env `PHAUST_CONFIG`.

| Section | Keys |
|---------|------|
| `[phaust]` | `name`, `iteration` |
| `[llm]` | `model`, `base_url`, `api_key`, `temperature`, `max_tokens` |
| `[llm.synthesis]` | Optional — explain-mode second pass (defaults to `[llm]`) |
| `[workspace]` | `root` |
| `[memory]` | `max_messages`, `compact_batch`, `max_episodes`, `semantic_top_k`, hybrid retrieval |
| `[agent]` | `agents_md`, `max_tool_rounds`, `max_write_proposals`, `require_write_approval` |
| `[tasks]` | `enabled`, `storage_dir`, `auto_checkpoint` |
| `[shell]` | `enabled`, `require_approval`, `allow`, … |

**Project rules:** [`AGENTS.md`](AGENTS.md) — identity, tool policy, shipped vs planned capabilities.

## LM Studio tips

- Disable **Enable Thinking** for Qwen 3.x if replies are empty or show long traces.
- Keep a **chat model loaded** for the whole session.
- Do not press **Enter** on an empty `You:` prompt (`400: No user query found`).

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `400` / “No user query found” | Corrupt context — restart Phaust (auto-repair) or clear `messages` in `Memory/phaust.db` |
| Edit without `read_file` on existing file | Tool error + recovery nudge — call `read_file` then retry |
| Answer stops after `read_file` on edits | Synthesis skipped for write intent — expected |
| `pip install` points at wrong venv | Delete `.venv`, recreate, `pip install -e .` again |

## Inspecting memory

```powershell
phaust recap
```

Or SQLite:

```powershell
sqlite3 Memory\phaust.db
```

```sql
SELECT key, value FROM facts;
SELECT substr(text, 1, 100), created_at FROM episodes ORDER BY created_at DESC LIMIT 5;
```

## Testing

```powershell
python -c "import tests.test_orchestration, tests.test_turn_runner, tests.test_recap, tests.test_tasks"
```

Unit tests are lightweight `python -c` style (no pytest required). Stress/regression notes: [`docs/STRESS_TESTS.md`](docs/STRESS_TESTS.md), log: `test_logging.txt`.

## What's next

See [docs/ROADMAP.md](docs/ROADMAP.md) — memory CLI, NL → task decomposition, per-task model profiles, `phaust resume`.

## License

Personal project — use and modify as you like.
