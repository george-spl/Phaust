# Phaust-2 architecture

Phaust-2 replaces ad-hoc regex and nudge logic inside `agent.py` with a small **orchestration** layer. The agent loop stays responsible for LLM I/O, tool execution, and approvals; orchestration decides *what kind of turn* this is and *which policies* apply.

## Layers

```
User message
    │
    ▼
┌─────────────────┐
│  intent.py      │  classify_turn() → TurnIntent (structured flags)
│  patterns.py    │  compiled patterns (single home for regex)
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│prompt_blocks │  │ policy.py    │  │ outcomes.py  │
│.py           │  │ nudges.py    │  │              │
└──────┬───────┘  └──────┬───────┘  └──────▲───────┘
       │                 │                  │
       └────────┬────────┘                  │
                ▼                           │
         ┌─────────────┐     tool results ──┘
         │ turn_loop   │  chat turn loop, nudges, outcomes
         └──────┬──────┘
                │
         ┌──────▼──────┐
         │  agent.py   │  session, memory, tool registration
         └─────────────┘
```

## Modules (`phaust/orchestration/`)

| Module | Responsibility |
|--------|----------------|
| `patterns.py` | All message-matching regex. New patterns go here only. |
| `intent.py` | `TurnIntent` + `classify_turn(message)`. One classifier per user turn. |
| `prompt_blocks.py` | Map `TurnIntent` → system prompt XML blocks (`<write_rules>`, `<brevity>`, …). |
| `policy.py` | Turn-loop decisions: skip synthesis, write-policy errors, nudge budgets. |
| `nudges.py` | Fixed nudge strings and refusal detectors. |
| `constants.py` | Tool name groupings for policy checks. |
| `outcomes.py` | Tool-round result formatting (write, shell, memory, read snapshots). |

## Design rules

1. **No new regex in `agent.py`.** Extend `patterns.py` and `classify_turn()`.
2. **No new nudge strings in `agent.py`.** Add to `nudges.py` and wire through `policy.py`.
3. **Prompt directives are data-driven.** `build_turn_directives(intent, …)` owns conditional system blocks.
4. **Behavior changes need a test.** See `tests/test_orchestration.py` and `tests/test_tasks.py`.

## Task mode (`phaust/tasks/`)

Multi-step work with persisted checkpoints under `Memory/tasks/` (gitignored).

| REPL command | Action |
|--------------|--------|
| `task` | List active, paused, and recent tasks |
| `task start Title :: step1 :: step2` | Start task ( `::` separates steps) |
| `task show` | Current step and checkpoints |
| `task step <text>` | Add a step |
| `task next [note]` | Complete step and advance |
| `task checkpoint [note]` | Manual checkpoint |
| `task pause` / `task resume [id]` | Pause and resume |
| `task done` / `task cancel` | Finish or abandon |

During an active task, each chat turn auto-checkpoints. The agent receives a `<task_mode>` system block with the current step.

## Semantic retrieval (`phaust/memory/retrieval.py`)

Cross-session file recall (e.g. `stress_c1.txt`) uses **hybrid ranking**:

1. Embedding similarity (API or bag-of-words fallback)
2. **Filename / artifact boost** when query mentions paths like `stress_c1.txt`
3. **Query expansion** — search `stress_c1.txt`, `stress_c1`, and related terms; merge best scores

Configure in `phaust.toml` `[memory]`: `hybrid_retrieval`, `filename_boost`, `lexical_weight`, `query_expansion`.

### Topic tags (`phaust/memory/topics.py`)

- `memorize` auto-tags episodes from content (e.g. `project`, `docs`, `design`, `notes`, …)
- `search_semantic` boosts scores when query tags match episode tags

### “Last time” conversations (`phaust/memory/last_session.py`)

When the user asks what you discussed last time (including “Hello Phaust. What were we…?”):

1. **`Memory/session_state.json`** — last topic, message previews, recent files, latest episode id (updated each turn)
2. **`<continue_from>`** — injected into the system prompt; preferred over older stress-test archives
3. **Recency ranking** — newer episodes score higher; dev/stress episodes demoted unless the query is about tests
4. **No “Hello Phaust” → stress search** — greeting the agent by name does not add `phaust` / `stress test` search terms

### Memory replies (policy)

- **Prose by default** — summarize in 2–5 sentences; do not paste raw `list_episodes` / `recall_episode` output unless the user asked for ids or raw text
- **Auto-return tool dumps** only for explicit commands (`recall user_job`, `list_episodes`, `search_semantic …`) or `recall <fact_key>`
- **Recall nudge** skipped when `<continue_from>` already has a session pointer; skipped for praise (“Good! Now you can recall…”)

## Turn loop (`phaust/turn_loop.py`)

- One user message → LLM rounds, tool execution, nudges, terminal outcomes
- `run_chat_turn(agent, message)` — called from REPL and tests via `agent.chat()`

## Turn runner (`phaust/turn_runner.py`)

- Explain-mode **synthesis** (second LLM pass from read/grep grounding)
- API message sanitization for LM Studio / Qwen
- Optional **`[llm.synthesis]`** profile in `phaust.toml` (falls back to main `[llm]`)

## Supporting modules

| Module | Role |
|--------|------|
| `prompt_context.py` | System prompt blocks (memory, task mode, directives) |
| `tool_executor.py` | Tool calls with write/shell approval and read-before-write gate |
| `reply.py` | Strip thinking blocks and meta-narration from replies |
| `repl.py` | Interactive `You:` session; slash `/resume`, `/recap`, `/help` |
| `resume.py` / `session_state.py` | `phaust resume` and per-turn session pointer |
| `recap.py` | `phaust recap` snapshot |
| `tool_ui.py` | Terminal formatting for tool results |
| `memory/last_session.py` | Last-time query detection and continue-from block |
| `memory/topics.py` | Topic tag inference for memorize and search |

## Tool recovery (`orchestration/policy.py`)

- After a tool round with recoverable errors (hint or read-before-write), one **recovery nudge** per turn retries instead of silent failure

## What stays in `agent.py`

- `Agent` dataclass: memory, workspace, tools, config
- Session lifecycle (`begin_session`, `finalize_session`, `_persist`)
- `chat()` → delegates to `turn_loop.run_chat_turn`

## Adding a new behavior

Example: “when user asks for X, nudge tool Y once”:

1. Add pattern(s) in `patterns.py` if needed.
2. Add flag(s) on `TurnIntent` in `intent.py`.
3. Add directive block in `prompt_blocks.py` if the model needs instructions.
4. Add `should_nudge_*` in `policy.py` and message in `nudges.py`.
5. Wire in `turn_loop.run_chat_turn()` using `NudgeBudget`.
6. Add a test in `tests/test_orchestration.py`.
