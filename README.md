# Phaust-1

**P**ractical **H**elper **A**utomated **U**tility **S**ystem — Iteration 1

A local, private AI agent that runs in your terminal. It uses a local LLM (via [LM Studio](https://lmstudio.ai) or any OpenAI-compatible server), SQLite memory, and workspace tools (read, grep, and approved writes).

## Requirements

- Python 3.11+
- A local LLM server at `http://127.0.0.1:1234` (default LM Studio port)
- A chat model loaded in the server (default: `qwen/qwen3.5-9b`)

## Setup

```powershell
cd D:\github\Phaust-1
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Start your LLM server, then:

```powershell
python main.py
```

Type `exit` or `quit` to end the session and archive memory.

## What it does

| Layer | Role |
|-------|------|
| **Context** | Recent chat (last 50 messages), session variables, live context (time, workspace) |
| **Long-term** | Explicit facts (`remember` / `recall` / `forget`) — user profile keys like `user_name` |
| **Semantic** | Searchable episode summaries from past conversations |

Older messages are auto-compacted into episodes (and only durable **user** facts) so memory stays small without losing the gist.

**Explain vs edit:** For “what does this file do?”, Phaust reads the file and answers from source (synthesis pass). For “write / edit / add a line”, it skips synthesis and uses the write path with diff approval.

## Tools

**Workspace**

- `read_file` — read a file under the project root (content is exact file text for use in `edit_file`)
- `list_files` — glob file listing
- `grep` — regex search in files
- `edit_file` — propose a single search/replace (unique `old_string`)
- `write_file` — propose create, overwrite, or clear (empty content)
- `delete_file` — propose removing a file from disk

**Write safety:** Every `edit_file` / `write_file` shows a full diff first. Nothing is written until you answer `y` to `Apply this change to disk? [y/N]`. Declining ends the turn and leaves the file unchanged.

Protected paths (no writes): `Memory/`, `.venv/`, `.git/`, `node_modules/`, etc. Allowed extensions include `.py`, `.md`, `.json`, `.txt`, `.yaml`, `.toml`.

**Memory**

- `remember`, `recall`, `forget`, `list_memories`
- `memorize`, `search_semantic`, `forget_semantic`
- `set_session`, `get_session`

**Private session:** Say e.g. `remember nothing this session` — Phaust blocks `remember` / `memorize` and discards the transcript on `exit` (no new facts or episodes).

## Project layout

```
main.py              Entry point, tool registration
phaust.toml          Runtime settings (model, memory limits, workspace)
phaust/
  config.py          Load phaust.toml
  prompts.py         Load AGENTS.md into system prompt
  agent.py           Chat loop, tool orchestration, synthesis, write flow
  tool_parse.py      Qwen/LM Studio XML tool-call fallback
  tools.py           Tool schema registry
  workspace.py       Read-only file tools
  workspace_write.py Edit/write with user approval
  memory/
    store.py         SQLite (phaust.db)
    context.py       Working / chat memory, session policy
    long_term.py     Key-value facts
    semantic.py      Episode search (embeddings + fallback)
    compaction.py    Summarize old chat into memory
docs/
  ROADMAP.md         Phaust-2 plans
Memory/
  phaust.db          Created at runtime (gitignored)
```

## Configuration

Edit **`phaust.toml`** in the project root (loaded on startup). Override path with env `PHAUST_CONFIG`.

| Section | Keys |
|---------|------|
| `[phaust]` | `name`, `iteration` |
| `[llm]` | `model`, `base_url`, `api_key`, `temperature`, `max_tokens` |
| `[workspace]` | `root` (relative to `phaust.toml`) |
| `[memory]` | `max_messages`, `compact_batch`, `max_episodes`, `semantic_top_k` |
| `[agent]` | `agents_md`, `max_tool_rounds`, `max_write_proposals`, `require_write_approval` |

**Project rules:** Edit [`AGENTS.md`](AGENTS.md) to change tone, tool behavior, and write policy (loaded every session). Set `agents_md = ""` in `phaust.toml` to disable and use a minimal built-in fallback.

## LM Studio tips

- Disable **Enable Thinking** for Qwen 3.x if replies are empty or show long “thinking” traces.
- Keep a **chat model loaded** for the whole session — unloading causes `(no response from model)`.
- Do not press **Enter** on an empty `You:` prompt — blank user turns break Qwen’s template (`400: No user query found`).

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `400` / “No user query found” | Empty user message in context — restart; Phaust skips blank input and cleans old rows on startup. |
| Plan to edit but no diff | Model replied with text only — one nudge, then XML tool blocks are parsed if needed. |
| Raw `<tool_call>` in the reply | Qwen text-format tools — parsed when possible; stripped from final text. |
| `n` loops forever | Fixed: one decline stops the turn; max 2 write previews per message. |
| Wrong line numbers (`7\|`, `2\|`) on write | Was caused by numbered read output — fixed: `read_file` returns exact disk text. |
| Answer stops after `read_file` on edits | Read-only synthesis — skipped when you asked for a file change. |

## Inspecting memory

```powershell
sqlite3 Memory\phaust.db
```

```sql
.tables
SELECT key, value FROM facts;
SELECT substr(text, 1, 100), created_at FROM episodes ORDER BY created_at DESC LIMIT 5;
.quit
```

Healthy facts: mostly `user_*` keys (name, job, company, hobbies). Task details belong in **episodes**, not facts.

## What's next

See [docs/ROADMAP.md](docs/ROADMAP.md) for **Phaust-2** (allowlisted shell, `AGENTS.md`, task mode, config file).

## License

Personal project — use and modify as you like.
