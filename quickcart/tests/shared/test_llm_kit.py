"""Tests for shared/llm_kit.py. No platform needed: _post is replaced with a fake."""
import json
from types import SimpleNamespace as NS

import pytest

from shared import llm_kit as kit
from shared import settings
from shared.testing import FakeLLM

TOOL = {"name": "get_order", "description": "Look up an order.",
        "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": []}}


def _resp(content="", tool_calls=None, finish="stop"):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5}}


@pytest.fixture
def platform(monkeypatch, tmp_path):
    """Configure a pretend platform and capture request bodies."""
    monkeypatch.setattr(settings, "LLM_BASE_URL", "http://platform.invalid/v1")
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(settings, "LLM_MODE", "live")
    monkeypatch.setattr(settings, "TOOL_MODE", "native")
    monkeypatch.setattr(settings, "JSON_MODE", "schema")
    monkeypatch.setattr(settings, "LLM_CACHE_DIR", tmp_path / "cache")
    sent = []
    responses = []

    def fake_post(path, body):
        sent.append((path, body))
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(kit, "_post", fake_post)
    return NS(sent=sent, responses=responses)


# ---- conversion: lab format -> OpenAI format ------------------------------------------------
def test_system_prompt_becomes_first_message():
    out = kit._to_openai([{"role": "user", "content": "hi"}], "You are helpful.", "vllm/mistral", False)
    assert out[0] == {"role": "system", "content": "You are helpful."}
    assert out[1] == {"role": "user", "content": "hi"}


def test_gemma_gets_system_text_inside_first_user_message():
    out = kit._to_openai([{"role": "user", "content": "hi"}], "Be brief.", "ollama/gemma2:2b", False)
    assert [m["role"] for m in out] == ["user"]
    assert out[0]["content"].startswith("Be brief.") and out[0]["content"].endswith("hi")


def test_tool_use_and_tool_result_blocks_convert_natively():
    msgs = [
        {"role": "user", "content": "Where is O101?"},
        {"role": "assistant", "content": [NS(type="tool_use", id="abc123def", name="get_order", input={"order_id": "O101"})]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "abc123def", "content": "not found",
                                      "is_error": True}]},
    ]
    out = kit._to_openai(msgs, "", "vllm/mistral", False)
    assert out[1]["tool_calls"][0]["function"] == {"name": "get_order", "arguments": json.dumps({"order_id": "O101"})}
    assert out[2] == {"role": "tool", "tool_call_id": "abc123def", "content": "ERROR: not found"}


def test_prompted_mode_renders_calls_and_results_as_text():
    msgs = [
        {"role": "assistant", "content": [NS(type="tool_use", id="x", name="get_order", input={})]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": {"status": "delivered"}}]},
    ]
    out = kit._to_openai(msgs, "", "vllm/mistral", True)
    assert "<tool_call>" in out[0]["content"]
    assert out[1]["role"] == "user" and "<tool_result" in out[1]["content"] and "delivered" in out[1]["content"]


def test_consecutive_user_messages_are_merged():
    out = kit._to_openai([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}], "", "vllm/m", False)
    assert out == [{"role": "user", "content": "a\n\nb"}]


# ---- conversion: OpenAI format -> Reply --------------------------------------------------------
def test_native_tool_calls_become_tool_use_blocks():
    resp = _resp(tool_calls=[{"id": "call00001", "type": "function",
                              "function": {"name": "get_order", "arguments": "{\"order_id\": \"O101\"}"}}],
                 finish="tool_calls")
    r = kit._from_openai(resp, "m", True, None, 0.1)
    assert r.stop_reason == "tool_use"
    assert (r.tool_calls[0].id, r.tool_calls[0].name, r.tool_calls[0].input) == ("call00001", "get_order", {"order_id": "O101"})
    assert (r.input_tokens, r.output_tokens) == (12, 5)


def test_text_tool_calls_are_parsed():
    r = kit._from_openai(_resp('Checking. <tool_call>{"name": "get_order", "arguments": {}}</tool_call>'), "m", True, None, 0)
    assert r.stop_reason == "tool_use" and r.tool_calls[0].name == "get_order" and r.text == "Checking."


def test_mistral_raw_tool_calls_are_parsed():
    r = kit._from_openai(_resp('[TOOL_CALLS] [{"name": "get_order", "arguments": {"order_id": "O1"}}]'), "m", True, None, 0)
    assert r.tool_calls[0].input == {"order_id": "O1"}


def test_length_finish_means_max_tokens():
    assert kit._from_openai(_resp("partial", finish="length"), "m", False, None, 0).stop_reason == "max_tokens"


def test_extract_json_handles_fences_and_lists():
    assert kit.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert kit.extract_json('Here: [{"intent": "query"}]') == [{"intent": "query"}]
    assert kit.extract_json("no json") is None


# ---- chat() behaviour ----------------------------------------------------------------------------
def test_chat_sends_tools_and_schema_natively(platform):
    platform.responses.append(_resp('{"intent": "query", "multiple_issues": false, "reason": "x"}'))
    r = kit.chat("Where is my order?", tools=[TOOL], schema={"type": "object"})
    path, body = platform.sent[0]
    assert path == "/chat/completions"
    assert body["tools"][0]["function"]["name"] == "get_order"
    assert body["response_format"]["type"] == "json_schema"
    assert r.data["intent"] == "query"


def test_chat_falls_back_to_prompted_mode_on_bad_request(platform):
    platform.responses.extend([kit._BadRequest(400, "tools not supported"), _resp("Hello")])
    r = kit.chat("hi", tools=[TOOL])
    second = platform.sent[1][1]
    assert "tools" not in second and "<tool_call>" in second["messages"][0]["content"]
    assert r.text == "Hello"


def test_no_fallback_raises_llm_error(platform):
    platform.responses.append(kit._BadRequest(400, "nope"))
    with pytest.raises(kit.LLMError):
        kit.chat("hi", tools=[TOOL], auto_fallback=False)


def test_gemma_with_tools_is_refused(platform):
    with pytest.raises(ValueError):
        kit.chat("hi", model="light", tools=[TOOL])


def test_record_then_replay(platform, monkeypatch):
    monkeypatch.setattr(settings, "LLM_MODE", "record")
    platform.responses.append(_resp(tool_calls=[{"id": "c1", "type": "function",
                                                 "function": {"name": "get_order", "arguments": "{}"}}]))
    first = kit.chat("Where is my order?", tools=[TOOL])
    monkeypatch.setattr(settings, "LLM_MODE", "replay")
    again = kit.chat("Where is my order?", tools=[TOOL])
    assert len(platform.sent) == 1                       # replay made no request
    assert again.tool_calls[0].name == first.tool_calls[0].name == "get_order"
    with pytest.raises(kit.ReplayMiss):
        kit.chat("Something never recorded")


def test_missing_config_is_explained(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BASE_URL", "")
    monkeypatch.setattr(settings, "LLM_MODE", "live")
    with pytest.raises(kit.LLMConfigError):
        kit._post("/chat/completions", {})


def test_embed_adds_nomic_prefixes(platform):
    platform.responses.append({"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
    assert kit.embed(["milk"], kind="query") == [[0.1, 0.2]]
    assert platform.sent[0][1]["input"] == ["search_query: milk"]


def test_batch_keeps_order():
    assert kit.batch(lambda x: x * 2, [3, 1, 2]) == [6, 2, 4]


def test_fake_llm_is_used_inside_context():
    with FakeLLM(["hello"]) as fake:
        assert kit.chat("hi").text == "hello"
    assert fake.calls[0]["messages"] == [{"role": "user", "content": "hi"}]
    assert kit._fake is None
