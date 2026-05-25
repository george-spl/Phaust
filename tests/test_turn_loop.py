"""Turn loop wiring tests."""

from phaust.agent import Agent
from phaust.orchestration import classify_turn
from phaust.turn_loop import TurnState, run_chat_turn


def test_agent_chat_delegates_to_turn_loop():
    agent = Agent(system_prompt="test")
    assert agent.chat is not None
    assert run_chat_turn.__name__ == "run_chat_turn"


def test_turn_state_from_intent():
    intent = classify_turn("Hello")
    state = TurnState(user_message="Hello", intent=intent)
    assert not state.wants_edit
    assert state.nudge_budget.recall == 0
