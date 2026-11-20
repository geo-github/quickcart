"""Data formats shared by all teams. FROZEN: a change needs one reviewer from each team.

The one rule every agent follows:

    def run(message: str, ctx: TurnContext) -> AgentResult

Conventions
- Messages use the Claude-style format from the labs: {"role": "user"|"assistant", "content": str | [blocks]}.
- Money is Decimal in code and a string such as "90.00" in JSON and in SQLite.
- Timestamps are UTC strings in SQLite's own format: "YYYY-MM-DD HH:MM:SS".
- Ids are prefixed: O101, SKU-PANEER-X-200, C-0001, T-0001, R-0001.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field, is_dataclass
from decimal import Decimal
from enum import Enum, StrEnum
from types import SimpleNamespace
from typing import Any, Callable

from shared import settings


class Role(StrEnum):
    CUSTOMER = "customer"
    OPERATOR = "operator"
    SYSTEM = "system"          # the complaint flow's own deterministic steps


INTENTS = ("query", "feedback", "complaint", "chitchat")
GUARD_VERDICTS = ("OK", "INJECTION", "OFF_TOPIC")
AGENT_STATUSES = ("ok", "stopped", "needs_approval", "blocked", "error")
TRACE_KINDS = ("decision", "tool_call", "tool_result", "retrieval", "policy", "guard", "limit", "error", "info")
COMPLAINT_TYPES = ("missing_item", "damaged", "late", "wrong_item", "other")
DECISION_ACTIONS = ("AUTO_REFUND", "NEEDS_APPROVAL", "REJECT", "ESCALATE")


@dataclass(frozen=True)
class TraceEvent:
    """One step shown in the CLI's live agent trace."""
    node: str                  # "router", "query_agent", "complaint.decide", ...
    kind: str                  # one of TRACE_KINDS
    detail: dict = field(default_factory=dict)


def _no_emit(event: TraceEvent) -> None:
    return None


def _default_budget() -> dict:
    return {"tokens_used": 0, "limit": settings.SESSION_TOKEN_BUDGET}


@dataclass
class TurnContext:
    """Everything an agent may know about the current turn. Built by Team 1's workflow;
    in tests, build one with shared.testing.make_ctx()."""
    user_id: str               # injected by our code, NEVER taken from the LLM
    session_id: str
    role: Role = Role.CUSTOMER
    history: list[dict] = field(default_factory=list)    # recent messages, lab (Claude) format
    summary: str | None = None                          # compaction summary (Lab 2D)
    memories: list[dict] = field(default_factory=list)  # [{"kind": "allergy", "content": "peanut"}, ...]
    emit: Callable[[TraceEvent], None] = _no_emit
    budget: dict = field(default_factory=_default_budget)  # {"tokens_used": int, "limit": int}

    def memory_values(self, kind: str) -> list[str]:
        """Remembered values of one kind, newest first, e.g. ctx.memory_values("allergy")."""
        return [m["content"] for m in self.memories if m.get("kind") == kind]


@dataclass
class Evidence:
    """A tool result, retrieved chunk or decision that an answer is based on.
    The output guard checks every number in the answer against these payloads."""
    source: str                # tool name, "policy", "verify", or a document source
    payload: Any


@dataclass
class AgentResult:
    """What EVERY agent returns."""
    answer: str
    evidence: list[Evidence] = field(default_factory=list)
    status: str = "ok"                    # one of AGENT_STATUSES
    handoff: str | None = None            # "complaint" when the feedback agent hands over (R4)
    handoff_note: str | None = None       # self-contained text for the next agent
    stats: dict = field(default_factory=dict)   # turns, tool_calls, tokens (Lab 2A)


@dataclass
class Facts:
    """Verified facts about a complaint (Team 3's verify step)."""
    order_found: bool
    order_belongs_to_user: bool
    item_in_order: bool | None            # None when the complaint type needs no item (late)
    item_sku: str | None
    item_price: Decimal | None
    delay_min: int | None
    refunds_last_30d: int
    already_refunded: bool


@dataclass
class Decision:
    """The policy engine's decision. The LLM only puts it into words."""
    action: str                           # one of DECISION_ACTIONS
    reason_code: str                      # machine-readable, e.g. "LATE_CREDIT"
    reason: str                           # human-readable
    amount: Decimal | None = None


ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "multiple_issues": {"type": "boolean"},
        "order_id": {"type": ["string", "null"]},
        "product": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
    "required": ["intent", "multiple_issues", "reason"],
}

COMPLAINT_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": list(COMPLAINT_TYPES)},
        "order_id": {"type": ["string", "null"]},
        "items": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"},
    },
    "required": ["type", "items", "description"],
}


def jsonable(obj: Any) -> Any:
    """Convert dataclasses, Decimals, enums, dates and SimpleNamespace blocks into plain JSON values."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Decimal):
        return format(obj, "f")
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (dt.datetime, dt.date)):
        return obj.isoformat(sep=" ") if isinstance(obj, dt.datetime) else obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, SimpleNamespace):
        return {k: jsonable(v) for k, v in vars(obj).items()}
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in obj]
    if hasattr(obj, "keys"):  # sqlite3.Row
        return {k: jsonable(obj[k]) for k in obj.keys()}
    return str(obj)
