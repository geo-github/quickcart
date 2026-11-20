"""llm_kit for the project: the lab helper, pointed at the training LLM platform.

Same interface as the lab `llm_kit`, so agent code is written exactly as in the labs:

    reply = kit.chat(messages, model="main", system=SYSTEM, tools=TOOLS)   # -> Reply
    reply.text, reply.content, reply.tool_calls (.id .name .input), reply.stop_reason, reply.data
    kit.batch(fn, items)                                                   # parallel workers (Lab 2B)
    kit.embed(texts, kind="document" | "query")                            # nomic-embed-text vectors

Messages and tools stay in the lab (Claude) format; this module converts them to the
platform's OpenAI-compatible format and back. Only the Python standard library is used.

Models:  "main"  = Mistral-7B-Instruct v0.3 (tools + JSON)   "light" = Gemma 2 2B (no tools)

LLM_MODE (in .env):
    live    call the platform
    record  call the platform and save every response under LLM_CACHE_DIR
    replay  never call the platform; serve saved responses (outside 11:00-21:00)
    cache   serve a saved response when there is one, otherwise call the platform and save it

TOOL_MODE: native (platform tool calling) | prompted (tools described in the prompt, calls
parsed from <tool_call>{...}</tool_call>). JSON_MODE: schema (response_format) | prompted.
Set both from the Day 1 smoke test: python tools/smoke_test.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from types import SimpleNamespace as NS
from typing import Any, Callable

from shared import settings
from shared.contracts import jsonable

log = logging.getLogger("llm_kit")


class LLMError(RuntimeError):
    """The platform call failed. The message never contains the key."""


class LLMConfigError(LLMError):
    """LLM_BASE_URL or LLM_API_KEY is missing."""


class ReplayMiss(LLMError):
    """LLM_MODE=replay and this exact call was never recorded."""


@dataclass
class Reply:
    content: list                 # blocks: NS(type="text", text=...) / NS(type="tool_use", id, name, input)
    text: str
    tool_calls: list
    stop_reason: str              # "end_turn" | "tool_use" | "max_tokens"
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    cost_usd: float = 0.0         # the platform has no per-call price; kept for lab compatibility
    data: Any = None              # parsed JSON when schema= was given

    @property
    def block_types(self) -> list[str]:
        return [b.type for b in self.content]


# ------------------------------------------------------------------------------------------
# Test hook: shared.testing.FakeLLM installs itself here
# ------------------------------------------------------------------------------------------
_fake: Any = None


def use_fake(fake: Any) -> None:
    """Route every chat()/embed() call to a fake (None to switch back to the platform)."""
    global _fake
    _fake = fake


def model_id(model: str) -> str:
    return {"main": settings.LLM_MAIN, "light": settings.LLM_LIGHT}.get(model, model)


# ------------------------------------------------------------------------------------------
# chat()
# ------------------------------------------------------------------------------------------
def chat(messages, model: str = "main", system=None, tools: list | None = None, schema: dict | None = None,
         max_tokens: int = 1024, temperature: float = 0.0, *, tool_mode: str | None = None,
         json_mode: str | None = None, auto_fallback: bool | None = None) -> Reply:
    """One model call. messages: a string, or a list of lab-format messages.
    system: a string (or a list of text blocks). tools: lab-format tool definitions
    ({"name", "description", "input_schema"}). schema: a JSON schema; the parsed result is in reply.data."""
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    if _fake is not None:
        return _fake.chat(messages=messages, model=model, system=system, tools=tools, schema=schema,
                          max_tokens=max_tokens)

    mid = model_id(model)
    if tools and "gemma" in mid.lower():
        raise ValueError("Gemma has no tool support. Use model='main' for anything with tools.")
    tool_mode = tool_mode or settings.TOOL_MODE
    json_mode = json_mode or settings.JSON_MODE
    fallback = settings.LLM_AUTO_FALLBACK if auto_fallback is None else auto_fallback

    key = _cache_key("chat", mid, messages, system, tools, schema, max_tokens, temperature)
    mode = settings.LLM_MODE
    if mode in ("replay", "cache"):
        saved = _load(key)
        if saved is not None:
            return _reply_from_saved(saved, mid)
        if mode == "replay":
            raise ReplayMiss(f"No recording for this exact call ({key[:12]}). Record it during 11:00-21:00 "
                             "with LLM_MODE=record or LLM_MODE=cache.")

    t0 = time.perf_counter()
    try:
        resp = _chat_request(messages, mid, system, tools, schema, max_tokens, temperature, tool_mode, json_mode)
    except _BadRequest as e:
        uses_native = (tools and tool_mode == "native") or (schema and json_mode == "schema")
        if not (fallback and uses_native):
            raise LLMError(f"Platform rejected the request (HTTP {e.status}): {e.detail}") from None
        log.warning("Platform rejected native tools/JSON (HTTP %s); retrying in prompted mode.", e.status)
        tool_mode = json_mode = "prompted"
        try:
            resp = _chat_request(messages, mid, system, tools, schema, max_tokens, temperature, tool_mode, json_mode)
        except _BadRequest as e2:
            raise LLMError(f"Platform rejected the request (HTTP {e2.status}): {e2.detail}") from None
    reply = _from_openai(resp, mid, bool(tools), schema, time.perf_counter() - t0)
    if mode in ("record", "cache"):
        _save(key, _reply_to_saved(reply))
    return reply


def _chat_request(messages, mid, system, tools, schema, max_tokens, temperature, tool_mode, json_mode) -> dict:
    prompted_tools = bool(tools) and tool_mode == "prompted"
    sys_text = _system_text(system)
    if prompted_tools:
        sys_text = _join(sys_text, _tool_prompt(tools))
    if schema and json_mode != "schema":
        sys_text = _join(sys_text, _json_prompt(schema))
    body: dict[str, Any] = {
        "model": mid,
        "messages": _to_openai(messages, sys_text, mid, prompted_tools),
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools and not prompted_tools:
        body["tools"] = [{"type": "function", "function": {
            "name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}}
            for t in tools]
    if schema and json_mode == "schema":
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}}
    return _post("/chat/completions", body)


# ------------------------------------------------------------------------------------------
# embed() and batch()
# ------------------------------------------------------------------------------------------
_EMBED_PREFIX = {"document": "search_document: ", "query": "search_query: "}


def embed(texts: str | list[str], kind: str = "document", batch_size: int = 64) -> list[list[float]]:
    """Embedding vectors from nomic-embed-text. kind="document" when indexing, "query" when searching
    (nomic expects these prefixes)."""
    if isinstance(texts, str):
        texts = [texts]
    if kind not in _EMBED_PREFIX:
        raise ValueError("kind must be 'document' or 'query'")
    inputs = [_EMBED_PREFIX[kind] + t for t in texts]
    if _fake is not None:
        return _fake.embed(inputs)
    vectors: list[list[float]] = []
    for i in range(0, len(inputs), batch_size):
        chunk = inputs[i:i + batch_size]
        key = _cache_key("embed", settings.EMBED_MODEL, chunk)
        mode = settings.LLM_MODE
        saved = _load(key) if mode in ("replay", "cache") else None
        if saved is None and mode == "replay":
            raise ReplayMiss(f"No recorded embeddings for this input ({key[:12]}). Record during 11:00-21:00.")
        if saved is None:
            resp = _post("/embeddings", {"model": settings.EMBED_MODEL, "input": chunk})
            rows = sorted(resp.get("data", []), key=lambda d: d.get("index", 0))
            saved = {"kind": "embed", "vectors": [r["embedding"] for r in rows]}
            if mode in ("record", "cache"):
                _save(key, saved)
        vectors.extend(saved["vectors"])
    return vectors


def batch(fn: Callable, items, workers: int = 4) -> list:
    """Apply fn to every item in parallel (Lab 2B), keeping the input order."""
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as pool:
        return list(pool.map(fn, items))


# ------------------------------------------------------------------------------------------
# HTTP
# ------------------------------------------------------------------------------------------
class _BadRequest(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status, self.detail = status, detail


def _post(path: str, body: dict) -> dict:
    base, key = settings.LLM_BASE_URL.rstrip("/"), settings.LLM_API_KEY
    if not base or not key:
        raise LLMConfigError("Set LLM_BASE_URL and LLM_API_KEY in .env (copy .env.example). "
                             "Or use LLM_MODE=replay / FakeLLM to work without the platform.")
    url = base + path
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "x-bf-vk": key}
    last = "unknown error"
    attempts = max(1, settings.LLM_MAX_RETRIES)
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=settings.LLM_TIMEOUT_S) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = _short(e.read(), key)
            if e.code in (400, 422):
                raise _BadRequest(e.code, detail) from None
            if e.code in (401, 403):
                raise LLMError(f"Platform refused the key (HTTP {e.code}). Check LLM_API_KEY in .env.") from None
            if e.code != 429 and e.code < 500:
                raise LLMError(f"Platform error (HTTP {e.code}): {detail}") from None
            last = f"HTTP {e.code}: {detail}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < attempts - 1:
            time.sleep(2 ** attempt)
    raise LLMError(f"Platform not reachable after {attempts} attempts ({last}). It is only available "
                   "11:00-21:00; outside that window use LLM_MODE=replay.")


def _short(raw: bytes, key: str) -> str:
    text = raw.decode("utf-8", errors="replace")[:300]
    return text.replace(key, "***") if key else text


# ------------------------------------------------------------------------------------------
# Format conversion: lab (Claude) format <-> OpenAI-compatible format
# ------------------------------------------------------------------------------------------
def _get(block, key, default=None):
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def _system_text(system) -> str:
    if not system:
        return ""
    if isinstance(system, list):
        return "\n\n".join(_get(b, "text", "") for b in system)
    return str(system)


def _join(a: str, b: str) -> str:
    return f"{a}\n\n{b}" if a else b


def _tool_prompt(tools: list) -> str:
    specs = "\n".join(json.dumps({"name": t["name"], "description": t.get("description", ""),
                                  "parameters": t["input_schema"]}) for t in tools)
    return ("You can call these tools:\n" + specs + "\n\n"
            "To call a tool, reply with one block per call and nothing else:\n"
            '<tool_call>{"name": "<tool name>", "arguments": {...}}</tool_call>\n'
            "Tool results come back inside <tool_result> blocks. When you have the answer, "
            "reply normally without any <tool_call> block.")


def _json_prompt(schema: dict) -> str:
    return "Return ONLY a JSON value matching this JSON schema, with no other text:\n" + json.dumps(schema)


def _to_openai(messages: list, sys_text: str, mid: str, prompted_tools: bool) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        role, content = m["role"], m["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        texts, calls, results = [], [], []
        for b in content:
            kind = _get(b, "type")
            if kind == "text":
                texts.append(_get(b, "text") or "")
            elif kind == "tool_use":
                calls.append((_get(b, "id"), _get(b, "name"), _get(b, "input") or {}))
            elif kind == "tool_result":
                res = _get(b, "content")
                res = res if isinstance(res, str) else json.dumps(jsonable(res), ensure_ascii=False)
                if _get(b, "is_error"):
                    res = "ERROR: " + res      # OpenAI format has no error flag
                results.append((_get(b, "tool_use_id"), res))
        if role == "assistant":
            if prompted_tools:
                parts = texts + [f'<tool_call>{json.dumps({"name": n, "arguments": a})}</tool_call>'
                                 for _, n, a in calls]
                out.append({"role": "assistant", "content": "\n".join(parts)})
            else:
                msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(texts) or (None if calls else "")}
                if calls:
                    msg["tool_calls"] = [{"id": i, "type": "function",
                                          "function": {"name": n, "arguments": json.dumps(a)}} for i, n, a in calls]
                out.append(msg)
        elif prompted_tools:
            parts = [f'<tool_result id="{i}">\n{r}\n</tool_result>' for i, r in results] + texts
            out.append({"role": "user", "content": "\n".join(parts)})
        else:
            out.extend({"role": "tool", "tool_call_id": i, "content": r} for i, r in results)
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
    out = _merge_consecutive(out)
    if sys_text:
        if "gemma" in mid.lower():   # Gemma has no system role: put it in the first user message
            for msg in out:
                if msg["role"] == "user" and isinstance(msg.get("content"), str):
                    msg["content"] = f"{sys_text}\n\n{msg['content']}"
                    break
            else:
                out.insert(0, {"role": "user", "content": sys_text})
        else:
            out.insert(0, {"role": "system", "content": sys_text})
    return out


def _merge_consecutive(msgs: list[dict]) -> list[dict]:
    """Mistral's template needs user/assistant turns to alternate: merge neighbours with the same role."""
    out: list[dict] = []
    for m in msgs:
        prev = out[-1] if out else None
        if (prev and prev["role"] == m["role"] and m["role"] in ("user", "assistant")
                and "tool_calls" not in prev and "tool_calls" not in m
                and isinstance(prev.get("content"), str) and isinstance(m.get("content"), str)):
            prev["content"] = f"{prev['content']}\n\n{m['content']}"
        else:
            out.append(dict(m))
    return out


_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def _new_call_id() -> str:
    return uuid.uuid4().hex[:9]          # Mistral expects 9-character ids


def _parse_args(args) -> dict:
    if isinstance(args, dict):
        return args
    try:
        parsed = json.loads(args or "{}")
        return parsed if isinstance(parsed, dict) else {"_invalid_arguments": args}
    except (json.JSONDecodeError, TypeError):
        return {"_invalid_arguments": args}


def _parse_text_tool_calls(raw: str) -> tuple[str, list]:
    """Tool calls written as text: <tool_call>{...}</tool_call> (prompted mode, as in the lab kit)
    or Mistral's raw "[TOOL_CALLS] [...]" when the server's tool parser is off."""
    calls = []
    for c in _TOOL_CALL_RE.findall(raw):
        try:
            d = json.loads(c)
        except json.JSONDecodeError:
            continue
        calls.append(NS(type="tool_use", id=_new_call_id(), name=d.get("name"), input=_parse_args(d.get("arguments"))))
    text = _TOOL_CALL_RE.sub("", raw).strip()
    if not calls and "[TOOL_CALLS]" in raw:
        head, _, payload = raw.partition("[TOOL_CALLS]")
        try:
            items = json.loads(payload.strip())
            items = items if isinstance(items, list) else [items]
            calls = [NS(type="tool_use", id=_new_call_id(), name=i.get("name"), input=_parse_args(i.get("arguments")))
                     for i in items if isinstance(i, dict)]
            text = head.strip()
        except json.JSONDecodeError:
            pass
    return text, calls


def _from_openai(resp: dict, mid: str, tools_given: bool, schema, latency: float) -> Reply:
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    raw = msg.get("content") or ""
    calls = [NS(type="tool_use", id=tc.get("id") or _new_call_id(), name=(tc.get("function") or {}).get("name"),
                input=_parse_args((tc.get("function") or {}).get("arguments")))
             for tc in msg.get("tool_calls") or []]
    text = raw.strip()
    if tools_given and not calls:
        text, calls = _parse_text_tool_calls(raw)
    content = ([NS(type="text", text=text)] if text else []) + calls
    finish = choice.get("finish_reason")
    stop = "tool_use" if calls else ("max_tokens" if finish == "length" else "end_turn")
    usage = resp.get("usage") or {}
    return Reply(content=content, text=text, tool_calls=calls, stop_reason=stop, model=mid,
                 input_tokens=int(usage.get("prompt_tokens") or 0), output_tokens=int(usage.get("completion_tokens") or 0),
                 latency_s=latency, data=extract_json(text) if schema else None)


def extract_json(text: str):
    """Parse JSON from model text; tolerant of ```json fences and surrounding words (from the lab kit)."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    starts = sorted(i for i in (t.find("{"), t.find("[")) if i >= 0)
    for start in starts:                       # try whichever bracket comes first
        closer = "}" if t[start] == "{" else "]"
        end = t.rfind(closer)
        if end > start:
            try:
                return json.loads(t[start:end + 1])
            except json.JSONDecodeError:
                continue
    return None


# ------------------------------------------------------------------------------------------
# Record / replay
# ------------------------------------------------------------------------------------------
def _cache_key(*parts) -> str:
    blob = json.dumps(jsonable(list(parts)), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load(key: str) -> dict | None:
    path = settings.LLM_CACHE_DIR / f"{key}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _save(key: str, payload: dict) -> None:
    settings.LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (settings.LLM_CACHE_DIR / f"{key}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                                        encoding="utf-8")


def _reply_to_saved(r: Reply) -> dict:
    return {"kind": "chat", "model": r.model, "text": r.text, "stop_reason": r.stop_reason,
            "tool_calls": [{"id": c.id, "name": c.name, "input": c.input} for c in r.tool_calls],
            "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "data": r.data}


def _reply_from_saved(s: dict, mid: str) -> Reply:
    calls = [NS(type="tool_use", id=c["id"], name=c["name"], input=c["input"]) for c in s.get("tool_calls", [])]
    content = ([NS(type="text", text=s["text"])] if s.get("text") else []) + calls
    return Reply(content=content, text=s.get("text", ""), tool_calls=calls, stop_reason=s["stop_reason"],
                 model=s.get("model", mid), input_tokens=s.get("input_tokens", 0),
                 output_tokens=s.get("output_tokens", 0), data=s.get("data"))
