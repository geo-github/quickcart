# QuickCart – Agentic Quick-Commerce Chatbot (Group 4)

A command-line chatbot for a quick-commerce store, built with the workshop's lab stack:
a router, Query and Feedback agents, a complaint flow with operator approval, guardrails and memory.
Each team's tasks, setup and merge steps are in its own work pack (Team 1, Team 2, Team 3).

## Setup (everyone)

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # macOS/Linux: cp .env.example .env
```

Fill in `LLM_BASE_URL` and `LLM_API_KEY` in `.env` (from your group leader; keep them confidential).

```bash
python -m data.seed                 # builds var/app.db with the demo data
pytest                              # all tests pass; no platform needed
```

## What's here

| Path | What | Owner |
|---|---|---|
| `shared/` | Contracts, LLM client, roles + audit, untrusted text, DB helpers, test helpers | Frozen (see "Changing a shared file") |
| `data/schema_core.sql`, `data/fixtures/core.json`, `data/seed.py` | Users, products, allergens, orders, audit log; the seed script | Frozen |
| `data/schema_assist.sql`, `data/fixtures/assist.json`, `data/docs/` | Reviews, feedback, policy documents | Team 2 |
| `data/schema_complaints.sql`, `data/fixtures/complaints.json` | Complaints, refunds, tickets, approvals | Team 3 |
| `data/schema_sessions.sql` | Sessions, messages, notices, memories | Team 1 |
| `orchestration/` | Router, orchestrator, chitchat, workflow, memory, output guard, CLI | Team 1 |
| `assist_agents/` | Query and Feedback agents, their tools, RAG | Team 2 |
| `complaints/` | Complaint flow, policy engine, approvals, input guard | Team 3 |
| `tools/smoke_test.py` | Platform check | Team 1 |
| `tests/` | `tests/shared/` plus one folder per team | Each team |

## Rules for everyone

- **The one rule:** every agent exposes `run(message: str, ctx: TurnContext) -> AgentResult` (see `shared/contracts.py`). Check yours with `shared.testing.assert_agent_contract`.
- **Lab stack only:** the standard library plus `requirements.txt`. Never add a package; anything new needs approval.
- **Models:** call them only through `shared/llm_kit.py`. `model="main"` is Mistral 7B (tools + JSON); `model="light"` is Gemma 2 2B (never give it tools).
- **The key and the URL are confidential.** They live only in your git-ignored `.env`: never in code, docs, chat, logs, traces or recordings.
- **Edit only your team's folder, your own data files and your tests.** More rules for coding assistants are in `CLAUDE.md`.

## Working outside 11:00–21:00

The platform only runs 11:00–21:00.

| When | `LLM_MODE` | What happens |
|---|---|---|
| 11:00–21:00 | `record` or `cache` | Real calls; responses saved under `var/llm_cache/` (`cache` reuses a saved one for an identical call) |
| Outside the window | `replay` | Saved responses only; a new call fails fast with "not recorded" |
| Any time | `FakeLLM` in unit tests | No platform needed |

To share recordings for scenario tests, copy them into `tests/replays/<team>/` and commit them (check them for secrets first).

## Branches and merges

- `main` always passes `pytest`. Each team works on `teamN/<feature>` branches and keeps an integration branch, `teamN/dev`.
- Pull `main` into your `dev` branch every morning.
- **Merge 1 (end of Day 3):** Team 2's agents replace Team 1's stand-ins. **Merge 2 (Day 4):** Team 3's complaint flow, input guard and approvals replace theirs. **Day 5:** everything switched on; feature freeze. Team 1 runs both merges; each team pack has its own merge checklist.

## Changing a shared file

`shared/`, `data/schema_core.sql`, `data/fixtures/core.json` and `data/seed.py` are frozen, because every team depends on them.

1. Tell Team 1 what you need and why.
2. If agreed, open a small PR changing only that file and its test in `tests/shared/`.
3. It needs one reviewer from each team.

Anything you can do inside your own folder (a helper, a table in your own schema file, more rows in your own fixture file) needs no shared change.
