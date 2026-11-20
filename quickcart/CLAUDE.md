# QuickCart agentic chatbot (Group 4)

CLI chatbot for a quick-commerce store: router, Query/Feedback agents, complaint flow, guards, memory.
Design docs live outside this repo (HLD, LLD, team work packs).

## Commands
- Setup: `python -m venv .venv`, activate it, `pip install -r requirements.txt`, copy `.env.example` to `.env`
- Seed the database: `python -m data.seed`
- Platform smoke test (11:00-21:00 only): `python tools/smoke_test.py`
- Tests: `pytest`

## Ownership
- `shared/`, `data/schema_core.sql`, `data/fixtures/core.json`: frozen; changes need one reviewer per team
- `orchestration/`: Team 1 · `assist_agents/`: Team 2 · `complaints/`: Team 3
- Edit only your team's folder, schema file, fixture file and tests

## Rules
- Lab stack only: standard library + packages in requirements.txt. Never add a package.
- Every agent exposes `run(message: str, ctx: TurnContext) -> AgentResult` (see shared/contracts.py)
- Call models only through `shared/llm_kit.py`. Gemma (`light`) never gets tools.
- `user_id` always comes from `ctx`, never from the LLM. Every customer query filters by it.
- Every tool runs through `shared.security.guarded()`
- Money is `Decimal`, stored as TEXT. Policy numbers live only in `complaints/policy/rules.py`
- SQL uses `?` placeholders only
- Customer-written text goes through `shared.untrusted` before reaching a prompt
- No secrets in code, logs, traces, recordings or the audit log. `.env` is never committed.
- IMPORTANT: never modify or delete an existing test to make it pass
- Never edit seed data to make a test pass
- Run `pytest` and show the output before saying a task is done
