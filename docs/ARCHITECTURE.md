# Phaust-2 architecture

Phaust-2 replaces ad-hoc regex and nudge logic inside `agent.py` with a small **orchestration** layer. The agent loop handles LLM I/O, tool execution, and approvals; orchestration decides *what kind of turn* this is and *which policies* apply.

## Layers

```
User message
    │
    ▼
┌─────────────────┐
│  intent.py      │  classify_turn() → TurnIntent
│  patterns.py    │  compiled patterns (single home for regex)
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│prompt_blocks │  │ policy.py    │  │ outcomes.py  │
└──────┬───────┘  └──────┬───────┘  └──────▲───────┘
       │                 │                  │
       └────────┬────────┘                  │
                ▼                           │
         ┌─────────────┐     tool results ──┘
         │ turn_loop   │
         └──────┬──────┘
                │
         ┌──────▼──────┐
         │  agent.py   │  session, memory, tools
         └─────────────┘
```

## Modules (`phaust/orchestration/`)

| Module | Responsibility |
|--------|----------------|
| `patterns.py` | All message-matching regex |
| `intent.py` | `TurnIntent` + `classify_turn(message)` |
| `prompt_blocks.py` | `TurnIntent` → system prompt blocks |
| `policy.py` | Synthesis skip, write policy, nudge budgets |
| `nudges.py` | Fixed nudge strings and refusal detectors |
| `constants.py` | Tool name groupings |
| `outcomes.py` | Format tool results for the user |

## Design rules

1. **No new regex in `agent.py`.** Extend `patterns.py` and `classify_turn()`.
2. **No new nudge strings in `agent.py`.** Add to `nudges.py` and wire through `policy.py`.
3. **Prompt directives are data-driven.** `build_turn_directives()` owns conditional blocks.
4. **Behaviour changes:** run relevant cases in `docs/STRESS_TESTS.md` and note results in `test_logging.txt` (and optional `tests/` import checks).

## Memory stack (`phaust/memory/`)

| Piece | Role |
|-------|------|
| `store.py` | SQLite: facts, episodes, messages, session kv |
| `long_term.py` | `remember` / `recall` facts |
| `semantic.py` | Episodes + `search_semantic`; uses `embedding_model` when set |
| `embeddings.py` | `/v1/embeddings` API or bag-of-words fallback |
| `compaction.py` | Summarize old messages → episode + optional facts |
| `context.py` | Working memory, opt-out, session finalize on exit |
| `retrieval.py` | Hybrid rank: embedding + lexical + filename boost |
| `topics.py` | Auto tags on `memorize` |
| `last_session.py` | Session pointer + “last time” bias |

### Embeddings vs chat model

`app.build_agent()` sets:

- `semantic.model` = `[llm].model` (chat)
- `semantic.embedding_model` = `[memory].embedding_model` when present in `phaust.toml`

If `embedding_model` is missing, embeddings use the chat model id (works only if that model supports `/embeddings`). **Load nomic (or similar) and set the id explicitly.**

## Task mode (`phaust/tasks/`)

Checkpoints under `Memory/tasks/` (gitignored). REPL: `task start Title :: step1 :: step2`, `task next`, `task pause` / `resume`, `task done`. Active tasks inject a `<task_mode>` system block.

## Turn loop (`phaust/turn_loop.py`)

One user message → LLM rounds, tools, nudges, terminal reply. `agent.chat()` → `run_chat_turn()`.

## Turn runner (`phaust/turn_runner.py`)

- Explain-mode **synthesis** from read/grep grounding
- `llm_extra()` → `chat_template_kwargs.enable_thinking: false` on chat/completions
- Optional **`[llm.synthesis]`** in `phaust.toml`

## Supporting modules

| Module | Role |
|--------|------|
| `prompt_context.py` | Assemble system prompt (memory, rules, directives) |
| `tool_executor.py` | Tools + write/shell approval |
| `reply.py` | Strip thinking blocks / meta preamble from replies |
| `repl.py` | Interactive session; `/resume` `/recap` `/help` |
| `resume.py` / `session_state.py` | Resume CLI + per-turn pointer |
| `recap.py` | `phaust recap` |
| `tool_ui.py` | Terminal tool traces |
| `tool_parse.py` | Parse `<tool_call>` text from models that emit XML |

## Tool recovery

One **recovery nudge** per turn on recoverable tool errors (e.g. read-before-write).

## What stays in `agent.py`

Session lifecycle, memory wiring, `chat()` delegation.

## Adding a new behavior

1. Pattern in `patterns.py` if needed.
2. Flag on `TurnIntent` in `intent.py`.
3. Directive in `prompt_blocks.py` if the model needs instructions.
4. Policy + nudge in `policy.py` / `nudges.py`.
5. Wire in `turn_loop.py`.
6. Manual check in `STRESS_TESTS.md` + optional test module under `tests/`.
