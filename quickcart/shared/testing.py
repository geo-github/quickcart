"""Test helpers so every team can test alone, without the platform or the other teams.

    from shared.testing import make_ctx, FakeLLM, build_test_db, assert_agent_contract

    def test_where_is_my_order(tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "DB_PATH", build_test_db(tmp_path))
        with FakeLLM([FakeLLM.tool("get_order", {}), FakeLLM.text("Your order O103 arrives at 10:10.")]) as fake:
            result = query_agent.run("Where is my order?", make_ctx("u1"))
        assert fake.calls[0]["tools"]          # the agent offered its tools
        assert result.evidence[0].source == "get_order"
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any, Callable

from shared import llm_kit, settings
from shared.contracts import AGENT_STATUSES, AgentResult, Evidence, Role, TraceEvent, TurnContext
from shared.llm_kit import Reply, extract_json


class RecordingEmitter:
    """Used as ctx.emit in tests: keeps every TraceEvent."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def __call__(self, event: TraceEvent) -> None:
        self.events.append(event)

    def of_kind(self, kind: str) -> list[TraceEvent]:
        return [e for e in self.events if e.kind == kind]


def make_ctx(user_id: str = "u1", *, session_id: str = "test-session", role: Role = Role.CUSTOMER,
             history: list[dict] | None = None, summary: str | None = None,
             memories: list[dict] | None = None, token_limit: int | None = None) -> TurnContext:
    """A TurnContext for tests. ctx.emit.events holds the emitted trace events.
    Example: make_ctx("u1", memories=[{"kind": "allergy", "content": "peanut"}])"""
    return TurnContext(user_id=user_id, session_id=session_id, role=role, history=list(history or []),
                       summary=summary, memories=list(memories or []), emit=RecordingEmitter(),
                       budget={"tokens_used": 0, "limit": token_limit or settings.SESSION_TOKEN_BUDGET})


class FakeLLM:
    """Scripted stand-in for the platform. Replies are returned in order; strings become text replies.
    Use as a context manager so it is removed again afterwards. Every call is kept in .calls."""

    def __init__(self, replies: list | None = None, *, handler: Callable[..., Reply | str] | None = None):
        self.queue = list(replies or [])
        self.handler = handler
        self.calls: list[dict] = []
        self.embed_calls: list[list[str]] = []

    # ---- building replies ---------------------------------------------------------------
    @staticmethod
    def text(text: str, *, input_tokens: int = 10, output_tokens: int = 10) -> Reply:
        return Reply(content=[NS(type="text", text=text)], text=text, tool_calls=[], stop_reason="end_turn",
                     model="fake", input_tokens=input_tokens, output_tokens=output_tokens)

    @staticmethod
    def tool(name: str, args: dict | None = None, *, text: str = "") -> Reply:
        return FakeLLM.tools((name, args or {}), text=text)

    @staticmethod
    def tools(*calls: tuple[str, dict], text: str = "") -> Reply:
        blocks = [NS(type="tool_use", id=f"call{i:05d}", name=n, input=a) for i, (n, a) in enumerate(calls)]
        content = ([NS(type="text", text=text)] if text else []) + blocks
        return Reply(content=content, text=text, tool_calls=blocks, stop_reason="tool_use", model="fake",
                     input_tokens=10, output_tokens=10)

    @staticmethod
    def json(data: Any) -> Reply:
        r = FakeLLM.text(json.dumps(data))
        r.data = data
        return r

    @staticmethod
    def truncated(text: str = "partial") -> Reply:
        r = FakeLLM.text(text)
        r.stop_reason = "max_tokens"
        return r

    # ---- what llm_kit calls -------------------------------------------------------------
    def chat(self, **kw) -> Reply:
        self.calls.append(kw)
        if self.handler is not None:
            reply = self.handler(**kw)
        elif self.queue:
            reply = self.queue.pop(0)
        else:
            raise AssertionError(f"FakeLLM ran out of scripted replies (call #{len(self.calls)}).")
        if isinstance(reply, str):
            reply = self.text(reply)
        if kw.get("schema") is not None and reply.data is None:
            reply.data = extract_json(reply.text)
        return reply

    def embed(self, inputs: list[str]) -> list[list[float]]:
        """Bag-of-words vectors: texts sharing words are close, so retrieval tests behave sensibly."""
        self.embed_calls.append(list(inputs))
        out = []
        for text in inputs:
            vec = [0.0] * 64
            for word in re.findall(r"[a-z0-9]+", text.lower().split(":", 1)[-1]):
                vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out

    def __enter__(self) -> "FakeLLM":
        llm_kit.use_fake(self)
        return self

    def __exit__(self, *exc) -> None:
        llm_kit.use_fake(None)


def build_test_db(tmp_dir: str | Path) -> Path:
    """Build a fresh seeded database in a temporary folder and return its path.
    Use with: monkeypatch.setattr(settings, "DB_PATH", build_test_db(tmp_path))"""
    from data import seed     # imported here so shared/ has no import-time dependency on data/

    return seed.build(Path(tmp_dir) / "app.db")


def assert_agent_contract(run: Callable[[str, TurnContext], AgentResult], message: str = "hello",
                          ctx: TurnContext | None = None) -> AgentResult:
    """Check that an agent follows the shared contract. Returns the result for further asserts."""
    result = run(message, ctx or make_ctx())
    assert isinstance(result, AgentResult), f"run() must return AgentResult, got {type(result).__name__}"
    assert isinstance(result.answer, str), "AgentResult.answer must be a string"
    assert result.status in AGENT_STATUSES, f"unknown status {result.status!r}"
    assert all(isinstance(e, Evidence) for e in result.evidence), "evidence must be a list of Evidence"
    assert result.handoff in (None, "complaint"), f"unknown handoff {result.handoff!r}"
    if result.handoff:
        assert result.handoff_note, "a handoff needs a handoff_note"
    return result


def assert_tools_hide_user_id(tools: list[dict]) -> None:
    """No tool definition may let the LLM choose whose data it reads (X5)."""
    for t in tools:
        props = t.get("input_schema", {}).get("properties", {})
        for banned in ("user_id", "role", "caller"):
            assert banned not in props, f"tool {t['name']} exposes '{banned}' to the LLM"
        assert t.get("description"), f"tool {t['name']} needs a description (it is the LLM's only guide)"
