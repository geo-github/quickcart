"""Day 1 platform smoke test. Run it once during 11:00-21:00:

    python tools/smoke_test.py

It checks each model, native vs prompted tool calls, forced JSON and embeddings, then tells you
which TOOL_MODE and JSON_MODE to put in .env. It never prints the key or the URL.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import llm_kit as kit  # noqa: E402
from shared import settings  # noqa: E402

TOOL = {
    "name": "get_order_status",
    "description": "Look up the delivery status of an order. Order ids look like O101.",
    "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
}
SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string", "enum": ["query", "complaint"]}, "reason": {"type": "string"}},
    "required": ["intent", "reason"],
}

results: list[tuple[str, bool, str, float]] = []


def check(name: str, fn) -> bool:
    t0 = time.perf_counter()
    try:
        ok, note = fn()
    except Exception as e:  # report every failure, keep going
        ok, note = False, f"{type(e).__name__}: {e}"
    results.append((name, ok, note, time.perf_counter() - t0))
    return ok


def chat_works(model: str):
    r = kit.chat("Reply with the single word: ready", model=model, max_tokens=10)
    return bool(r.text), repr(r.text[:40])


def tool_call(mode: str):
    r = kit.chat("What is the status of order O101? Use the tool.", model="main", tools=[TOOL],
                 tool_mode=mode, auto_fallback=False, max_tokens=200)
    calls = [(c.name, c.input) for c in r.tool_calls]
    ok = bool(calls) and calls[0][0] == "get_order_status" and calls[0][1].get("order_id") == "O101"
    return ok, f"calls={calls}" if calls else f"no tool call; text={r.text[:60]!r}"


def json_output(mode: str):
    r = kit.chat("Classify: 'My eggs were missing from the order.'", model="main", schema=SCHEMA,
                 json_mode=mode, auto_fallback=False, max_tokens=200)
    ok = isinstance(r.data, dict) and r.data.get("intent") in ("query", "complaint")
    return ok, f"data={r.data}" if r.data else f"unparseable: {r.text[:60]!r}"


def embedding():
    vecs = kit.embed(["where is my order"], kind="query")
    return bool(vecs and vecs[0]), f"dimension={len(vecs[0]) if vecs else 0}"


def main() -> int:
    settings.LLM_MODE = "live"       # always hit the platform, never the recordings
    if not settings.LLM_BASE_URL or not settings.LLM_API_KEY:
        print("LLM_BASE_URL and LLM_API_KEY are not set. Copy .env.example to .env and fill them in.")
        return 2
    print(f"Models: main={settings.LLM_MAIN}  light={settings.LLM_LIGHT}  embed={settings.EMBED_MODEL}\n")
    basic = check("chat: main model", lambda: chat_works("main"))
    check("chat: light model", lambda: chat_works("light"))
    native_tools = check("tools: native", lambda: tool_call("native"))
    prompted_tools = check("tools: prompted", lambda: tool_call("prompted"))
    native_json = check("json: schema (response_format)", lambda: json_output("schema"))
    prompted_json = check("json: prompted", lambda: json_output("prompted"))
    check("embeddings", embedding)

    for name, ok, note, secs in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<32} {secs:5.1f}s  {note}")
    print()
    print(f"Put in .env:  TOOL_MODE={'native' if native_tools else 'prompted'}"
          f"   JSON_MODE={'schema' if native_json else 'prompted'}")
    if not (native_tools or prompted_tools):
        print("WARNING: no tool-call mode worked. Share this output with Team 1.")
    if not (native_json or prompted_json):
        print("WARNING: no JSON mode worked reliably. The router and extractor will need validate-and-retry.")
    return 0 if basic else 1


if __name__ == "__main__":
    sys.exit(main())
