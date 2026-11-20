"""Tests for shared/contracts.py and shared/testing.py."""
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from shared.contracts import AgentResult, Decision, Evidence, TraceEvent, jsonable
from shared.testing import FakeLLM, assert_agent_contract, assert_tools_hide_user_id, make_ctx


def test_jsonable_handles_decimals_dataclasses_and_blocks():
    d = Decision("AUTO_REFUND", "WITHIN_LIMIT", "within limit", Decimal("90.00"))
    assert jsonable(d) == {"action": "AUTO_REFUND", "reason_code": "WITHIN_LIMIT", "reason": "within limit", "amount": "90.00"}
    assert jsonable(NS(type="text", text="hi")) == {"type": "text", "text": "hi"}


def test_make_ctx_records_events_and_memories():
    ctx = make_ctx("u2", memories=[{"kind": "allergy", "content": "peanut"}])
    ctx.emit(TraceEvent("router", "decision", {"intent": "query"}))
    assert ctx.emit.events[0].node == "router"
    assert ctx.memory_values("allergy") == ["peanut"] and ctx.user_id == "u2"


def test_fake_llm_scripts_replies_and_parses_json():
    with FakeLLM([FakeLLM.tool("get_order", {"order_id": "O101"}), '{"intent": "query"}']) as fake:
        from shared import llm_kit as kit
        first = kit.chat("where?", tools=[{"name": "get_order"}])
        second = kit.chat("classify", schema={"type": "object"})
    assert first.stop_reason == "tool_use" and first.tool_calls[0].input == {"order_id": "O101"}
    assert second.data == {"intent": "query"} and len(fake.calls) == 2


def test_fake_llm_runs_out_loudly():
    with FakeLLM([]):
        from shared import llm_kit as kit
        with pytest.raises(AssertionError, match="ran out"):
            kit.chat("hi")


def test_fake_embeddings_put_similar_texts_close():
    fake = FakeLLM()
    a, b, c = fake.embed(["search_query: paneer reviews", "search_document: paneer review summary",
                          "search_document: refund policy"])
    dot = lambda x, y: sum(p * q for p, q in zip(x, y))
    assert dot(a, b) > dot(a, c)


def test_agent_contract_helper_accepts_a_good_agent():
    def agent(message, ctx):
        return AgentResult("ok", [Evidence("get_order", {"order_id": "O101"})])
    assert assert_agent_contract(agent).answer == "ok"


def test_agent_contract_helper_rejects_handoff_without_note():
    with pytest.raises(AssertionError, match="handoff_note"):
        assert_agent_contract(lambda m, c: AgentResult("x", handoff="complaint"))


def test_tool_schemas_must_not_expose_user_id():
    with pytest.raises(AssertionError, match="user_id"):
        assert_tools_hide_user_id([{"name": "bad", "description": "x",
                                    "input_schema": {"properties": {"user_id": {"type": "string"}}}}])
