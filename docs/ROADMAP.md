# Phaust roadmap

## Phaust-1 (current)

- Local console agent, SQLite memory, workspace read/write with approval
- Grounded answers after `read_file` (explain mode)
- Write path: intent detection, single nudge, XML tool-call parsing, clean post-write replies

## Phaust-2 (in progress on `experimental`)

| Area | Status |
|------|--------|
| **Config** | Done — `phaust.toml` + `phaust/config.py` |
| **Rules** | Done — `AGENTS.md` + `phaust/prompts.py` |
| **Shell** | Planned — `run_command` with allowlisted commands, cwd jail, timeout, output cap |
| **Tasks** | Multi-step task mode with checkpoints and resume |
| **Memory** | Smarter fact keys (user vs agent identity), optional memory review UI |
| **Models** | Per-task model profiles (fast vs reasoning) |
| **Packaging** | Optional `phaust` CLI entry point, config file instead of editing `agent.py` |

Contributions and experiments welcome on branch `experimental`.
