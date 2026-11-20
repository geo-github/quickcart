"""Roles and audit log for every tool (W1). Lab 2C TODO 5 and 6, as plain Python.

Every tool body runs through guarded():

    def get_order(ctx, order_id=None):
        return guarded("get_order", {"order_id": order_id}, ctx, Role.CUSTOMER,
                       lambda: catalog_sql.order_for_user(ctx.user_id, order_id))

- require() refuses callers without an identity or with too low a role, with an instructive message.
- audit() writes one audit_log row for every write and every refusal. It never stores secrets.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Callable

from shared import db
from shared.contracts import Role, TurnContext, jsonable

RANK = {Role.CUSTOMER: 1, Role.OPERATOR: 2, Role.SYSTEM: 3}

# Tools that change data: always audited when they succeed.
WRITE_TOOLS = frozenset({"submit_feedback", "create_complaint", "issue_refund", "create_ticket"})

_SECRET_HINTS = ("key", "token", "password", "secret", "authorization")


def require(ctx: TurnContext | None, role: Role) -> None:
    if ctx is None or not getattr(ctx, "user_id", None):
        raise PermissionError("Unauthorized: no caller identity. This tool needs a logged-in caller.")
    if RANK.get(Role(ctx.role), 0) < RANK[role]:
        raise PermissionError(f"Forbidden: this tool needs role '{role.value}', but the caller is "
                              f"'{Role(ctx.role).value}'. Do not retry; refunds and other protected actions "
                              "are handled by the complaint process.")


def _redact(args: dict) -> dict:
    return {k: ("***" if any(h in k.lower() for h in _SECRET_HINTS) else v) for k, v in (args or {}).items()}


def audit(ctx: TurnContext | None, tool: str, args: dict, ok: bool, detail: str = "") -> None:
    db.execute(
        "INSERT INTO audit_log (ts, user, role, tool, args, ok, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (db.utcnow(),
         getattr(ctx, "user_id", None) or "anonymous",
         Role(ctx.role).value if ctx is not None else None,
         tool,
         json.dumps(jsonable(_redact(args)), ensure_ascii=False),
         int(ok),
         detail[:500]),
    )


def guarded(tool: str, args: dict, ctx: TurnContext | None, min_role: Role, action: Callable[[], Any],
            *, write: bool | None = None) -> Any:
    """Check the role, run the action, audit writes and refusals. Domain errors (ValueError etc.)
    raised by the action propagate unchanged, so the agent loop can return them as is_error results."""
    is_write = tool in WRITE_TOOLS if write is None else write
    try:
        require(ctx, min_role)
    except PermissionError as e:
        audit(ctx, tool, args, ok=False, detail=str(e))
        raise
    out = action()
    if is_write:
        audit(ctx, tool, args, ok=True)
    return out


def with_role(ctx: TurnContext, role: Role) -> TurnContext:
    """A copy of ctx acting with another role, e.g. with_role(ctx, Role.SYSTEM) inside the complaint flow."""
    return replace(ctx, role=role)


def operator_context(operator: str, session_id: str = "operator-console") -> TurnContext:
    """Context for an operator acting from the CLI (demo only: no login)."""
    return TurnContext(user_id=operator, session_id=session_id, role=Role.OPERATOR)
