"""Turn runner and tool recovery tests."""

from phaust.orchestration.policy import (
    build_tool_recovery_nudge,
    is_recoverable_tool_error,
    should_nudge_tool_recovery,
)
from phaust.orchestration.policy import NudgeBudget
from phaust.reply import clean_reply, is_meta_narration
from phaust.turn_runner import (
    grounding_from_tool_results,
    merge_consecutive_users,
    sanitize_messages_for_api,
)


def test_grounding_skips_errors():
    text = grounding_from_tool_results(
        [
            {"error": "missing"},
            {"path": "a.py", "content": "x = 1", "total_lines": 1},
        ]
    )
    assert "a.py" in text
    assert "missing" not in text


def test_recoverable_read_before_write():
    result = {
        "error": "Call read_file on this path before edit_file/delete_file",
        "path": "foo.py",
        "hint": "For a NEW file use create_file",
    }
    assert is_recoverable_tool_error(result)
    nudge = build_tool_recovery_nudge([result])
    assert nudge and "read_file" in nudge


def test_tool_recovery_budget_once():
    budget = NudgeBudget(tool_recovery=1)
    assert not should_nudge_tool_recovery(
        [{"error": "x", "hint": "y"}], budget
    )


def test_clean_reply_strips_think():
    out = clean_reply("Hello <thinking>secret</thinking> world")
    assert "secret" not in out
    assert "world" in out


def test_meta_narration_detected():
    assert is_meta_narration("The user is asking me to refactor the module.")


def test_sanitize_requires_user():
    msgs = sanitize_messages_for_api(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    )
    assert any(m["role"] == "user" for m in msgs)


def test_merge_consecutive_users():
    merged = merge_consecutive_users(
        [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ]
    )
    assert len(merged) == 1
    assert "a" in merged[0]["content"] and "b" in merged[0]["content"]
