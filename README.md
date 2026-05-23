# Phaust-1

**P**ractical **H**elper **A**utomated **U**tility **S**ystem — Iteration 1

A local, private AI agent that runs in your terminal. It uses a local LLM (via [LM Studio](https://lmstudio.ai) or any OpenAI-compatible server), persistent SQLite memory, and read-only workspace tools.

## Requirements

- Python 3.11+
- A local LLM server at `http://LOCALHOST:1234` (default LM Studio port)
- Model loaded in the server (default config: `qwen/qwen3.5-9b`)

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
| **Long-term** | Explicit facts (`remember` / `recall` / `forget`) |
| **Semantic** | Searchable episode summaries from past conversations |

Older messages are auto-compacted into semantic episodes and facts so memory stays small without losing the gist.

## Tools

**Workspace**

- `read_file` — read a file under the project root
- `list_files` — glob file listing
- `grep` — regex search in files
- `edit_file` — propose a single search/replace (unique `old_string`)
- `write_file` — propose create or full overwrite

**Write safety:** Every `edit_file` / `write_file` shows a full diff in the terminal first. Nothing is written until you answer `y` to `Apply this change to disk? [y/N]`. Declining leaves files unchanged.

Protected paths (no writes): `Memory/`, `.venv/`, `.git/`, `node_modules/`, etc. Allowed extensions include `.py`, `.md`, `.json`, `.txt`, `.yaml`, `.toml`.

**Memory**

- `remember`, `recall`, `forget`, `list_memories`
- `memorize`, `search_semantic`, `forget_semantic`
- `set_session`, `get_session`

For code questions, Phaust reads the file first, then answers from the source (synthesis pass) to reduce hallucination.

## Project layout

```
main.py              Entry point, tool registration
phaust/
  agent.py           Chat loop, tool orchestration, synthesis
  tools.py           Tool schema registry
    workspace.py       Read-only file tools
    workspace_write.py Edit/write with user approval
  memory/
    store.py         SQLite (phaust.db)
    context.py       Working / chat memory
    long_term.py     Key-value facts
    semantic.py      Episode search (embeddings)
    compaction.py    Summarize old chat into memory
Memory/
  phaust.db          Created at runtime (gitignored)
```

## Configuration

Edit defaults in `phaust/agent.py` or pass options when building the agent in `main.py`:

- `model` — model id your server expects
- `base_url` — API base (default `http://127.0.0.1:1234/v1`)
- `workspace_root` — `WORKSPACE_ROOT` in `main.py` (default: project folder)

## LM Studio tips

- Disable **Enable Thinking** for Qwen 3.x if replies are empty or show long “thinking” traces.
- Ensure the server is running before starting Phaust.

## Inspecting memory

```powershell
sqlite3 Memory\phaust.db
```

```sql
.tables
SELECT * FROM facts;
SELECT substr(text, 1, 80), created_at FROM episodes;
.quit
```

## License

Personal project — use and modify as you like.