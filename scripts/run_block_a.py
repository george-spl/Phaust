"""Run Block A session etiquette tests against live Phaust + LM Studio."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from phaust.app import build_agent  # noqa: E402


def has_greeting(text: str) -> bool:
    return bool(
        re.search(
            r"\b(hello|good (?:day|morning|evening)|how can I help|how may I assist)\b",
            text,
            re.I,
        )
    )


def has_re_greet(text: str) -> bool:
    return bool(
        re.search(
            r"\b(hello again|good to see you|good to see you again|hello,?\s+\w+[!.]?\s*(?:how|what|that sounds))\b",
            text,
            re.I,
        )
    ) or (has_greeting(text) and re.search(r"\bhello\b", text, re.I))


def is_meta_narration(text: str) -> bool:
    from phaust.agent import Agent

    return Agent._is_meta_narration(text)


def memory_disabled(ctx) -> bool:
    return not ctx.memory_writes_enabled()


def run_block_a() -> list[dict]:
    results: list[dict] = []
    agent = build_agent()
    agent.begin_session()

    # A1
    r1 = agent.chat("Hello Phaust")
    a1_pass = has_greeting(r1) and len(r1) < 500
    results.append(
        {
            "id": "A1",
            "pass": a1_pass,
            "note": "Brief greeting" if a1_pass else f"Unexpected: {r1[:120]}…",
            "reply": r1,
        }
    )

    # A2
    r2 = agent.chat("What tools do you have?")
    a2_pass = not has_re_greet(r2) and "tool" in r2.lower()
    results.append(
        {
            "id": "A2",
            "pass": a2_pass,
            "note": "No re-greet; mentions tools"
            if a2_pass
            else f"Re-greet or weak reply: {r2[:120]}…",
            "reply": r2,
        }
    )

    # A3
    r3 = agent.chat("You don't remember our last session?")
    a3_pass = not memory_disabled(agent.context_memory) and not is_meta_narration(r3)
    results.append(
        {
            "id": "A3",
            "pass": a3_pass,
            "note": "Memory still on; no meta-only"
            if a3_pass
            else f"Memory off={memory_disabled(agent.context_memory)} meta={is_meta_narration(r3)}",
            "reply": r3,
        }
    )

    # A4 — substantive question
    r4 = agent.chat(
        "Today we will run comprehensive tests from docs/STRESS_TESTS.md. Ready?"
    )
    a4_pass = not is_meta_narration(r4) and not has_re_greet(r4)
    results.append(
        {
            "id": "A4",
            "pass": a4_pass,
            "note": "Direct reply, no meta narration"
            if a4_pass
            else f"Meta or re-greet: {r4[:120]}…",
            "reply": r4,
        }
    )

    # A5 — new session
    agent.finalize_session()
    agent.begin_session()
    r5 = agent.chat("Hello Phaust")
    a5_pass = has_greeting(r5)
    results.append(
        {
            "id": "A5",
            "pass": a5_pass,
            "note": "Greets again in new session"
            if a5_pass
            else f"No greeting: {r5[:120]}…",
            "reply": r5,
        }
    )

    return results


def main() -> int:
    print("Block A — Session etiquette (live LLM required)\n")
    try:
        results = run_block_a()
    except Exception as e:
        print(f"FAILED to run: {e}")
        print("Is LM Studio running with qwen/qwen3.5-9b loaded?")
        return 1

    passed = sum(1 for r in results if r["pass"])
    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"[{r['id']}] {status} — {r['note']}")
        print(f"      Agent: {r['reply'][:200].replace(chr(10), ' ')}…\n")

    print(f"Block A score: {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
