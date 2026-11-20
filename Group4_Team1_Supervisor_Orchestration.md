# Team 1 – Supervisor & Orchestration

> **You build the brain and the front door:** the router that decides who handles each message, the orchestrator for messages with several requests, chitchat, the workflow that connects every agent, sessions and memory, the output guard, and the CLI. You also lead both merges.

| | |
|---|---|
| **Members** | 2 members (you decide how to divide the tasks) |
| **Your agents** | Router · Orchestrator · Chitchat (+ memory extractor) |
| **Your folder** | `orchestration/` (plus `data/schema_sessions.sql`, `evals/`, `tests/orchestration/`) |
| **Spec items** | X1, X3, X4, W3, W4, W6, A1–A3 (optional) |
| **Demo scenarios** | #11 off-topic · #14 memory · #16 limits · the multi-request message |
| **Labs you reuse** | 2B (router, orchestrator) · 2D (compaction, memory) · 1A (model comparison) |
| **Cross-team role** | Team 1 runs both merges, reviews Team 2 and Team 3 PRs, and decides on shared-file changes |

Background: [High-level design](Group4_QuickCommerce_HLD.md) · [Low-level design §3.6](Group4_QuickCommerce_Agentic_Design.md) · repository rules in `quickcart/README.md`

---

## 0. Setup (Day 1, about 30 minutes)

**Each member:**

```bash
cd quickcart
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # then fill in LLM_BASE_URL and LLM_API_KEY (confidential)
python -m data.seed                 # builds var/app.db with the demo data
pytest                              # the shared tests pass
git checkout -b team1/dev
```

**Once for the team, inside 11:00–21:00:**

```bash
python tools/smoke_test.py
```

It prints `TOOL_MODE=…` and `JSON_MODE=…`. Put them in `.env.example`, commit, and tell Teams 2 and 3. Nobody has to wait for this: the defaults work, and `llm_kit` falls back to prompted mode if the platform rejects native tool calls or JSON.

Create your folders: `orchestration/prompts/`, `tests/orchestration/`, `evals/`.

---

## 1. Your starting point (already in the repo)

| File | What it gives you |
|---|---|
| `shared/contracts.py` | `TurnContext`, `AgentResult`, `Evidence`, `TraceEvent`, `ROUTER_SCHEMA`, `INTENTS`, `GUARD_VERDICTS` |
| `shared/llm_kit.py` | `kit.chat(...)`, `kit.batch(...)`, `kit.extract_json(...)`; record/replay via `LLM_MODE` |
| `shared/settings.py` | `MAX_STEPS`, `SESSION_TOKEN_BUDGET`, `HISTORY_TOKEN_BUDGET`, `ENABLE_ORCHESTRATOR`, `GUARDS_ENABLED` |
| `shared/db.py` | `query`, `query_one`, `execute`, `transaction`, `utcnow` |
| `shared/testing.py` | `make_ctx`, `FakeLLM`, `build_test_db`, `assert_agent_contract` |
| `data/schema_sessions.sql` | **Your** tables, as a first draft: `sessions`, `messages`, `notices`, `memories` |
| `tools/smoke_test.py` | The platform check you run on Day 1 |

You own and may change `data/schema_sessions.sql`. Everything in `shared/` is frozen ("Changing a shared file" in `quickcart/README.md`). Other teams bring change requests to Team 1.

---

## 2. Your responsibilities

**Inside your slice:**
- The router, the orchestrator and chitchat
- The workflow that connects every agent, with stand-ins until the merges
- Sessions, compaction and long-term memory
- The output guard
- The chat service and the CLI
- The evaluation runner and report

**For the whole group:**
- Run the platform smoke test and share the settings
- Run both merges and the Day 5 integration
- Review Team 2 and Team 3 PRs (about an hour a day)
- Decide on requests to change a shared file
- Run the daily 11:00 sync

---

## 3. Tech stack

| Need | Use |
|---|---|
| Model calls | `shared/llm_kit.py`: `model="main"` (Mistral 7B) for router, orchestrator, synthesiser, compaction, memory extraction; `model="light"` (Gemma 2 2B, no tools) for chitchat |
| Parallel workers | `kit.batch` |
| Sessions and memory | SQLite through `shared/db.py` |
| Grounding check | `re`, `decimal` (standard library) |
| CLI | `argparse`, `input()`, `print()` (standard library) |
| Tests | `pytest`, `shared.testing` |

You don't need ChromaDB or FastMCP.

---

## 4. Your tasks

| ID | Task | Done when |
|---|---|---|
| T1.1 | Run `python tools/smoke_test.py` in the platform window; put the suggested `TOOL_MODE` / `JSON_MODE` in `.env.example`; share the output | All six people have the settings |
| T1.2 | `orchestration/stubs.py`: stand-ins for `query`, `feedback`, `complaint`, `input_guard.check` and approvals, with the exact signatures in §6 | Each stub passes `assert_agent_contract` |
| T1.3 | `workflow.py`: `handle_turn()` (§5.1) | Workflow tests in §8 pass with stubs |
| T1.4 | `router.py` + `prompts/router.md` + `evals/router_set.jsonl` (30 labelled messages) | Accuracy reported for Gemma and Mistral; model chosen |
| T1.5 | `orchestrator.py`: decompose → `kit.batch` → synthesise (§5.3) | The multi-request demo gives one reply covering every part |
| T1.6 | `sessions.py`: create, load, append, `context()`, `post_notice()`, `finish()` | A session survives a restart of the CLI |
| T1.7 | `memory.py`: `compact()`, `remember()`, `recall()`, `extract_memories()` (§5.4) | Demo #14 passes; `u2` never sees `u1`'s memories |
| T1.8 | `output_guard.py` + `grounding.py` (§5.5) | An ungrounded number is retried once, then replaced |
| T1.9 | `chitchat.py` + `prompts/chitchat.md` | Demo #11 gets a polite redirect |
| T1.10 | `service.py` (`ChatService`) + `cli.py` (§5.6) | The full CLI works end to end on stubs |
| T1.11 | `evals/run_evals.py`: router accuracy, groundedness, injection block rate; guards off vs on | Results table committed |
| T1.12 | Merge 1 and Merge 2 (§10) | Tags `merge-1`, `merge-2` exist |

---

## 5. Design details

### 5.1 Workflow

```python
AGENTS = {"query": stubs.query_run, "feedback": stubs.feedback_run,       # swapped at Merge 1
          "complaint": stubs.complaint_run, "chitchat": chitchat.run}     # complaint swapped at Merge 2
input_guard = stubs                                                       # complaints.input_guard at Merge 2

def handle_turn(session_id: str, message: str, emit) -> AgentResult:
    s = sessions.load(session_id)
    ctx = sessions.context(s, emit)                    # TurnContext: user_id, history, summary, memories, budget
    sessions.append(s, "user", message)
    ctx.summary, ctx.history = memory.compact(s)
    verdict = "OK"
    if settings.GUARDS_ENABLED:
        verdict = input_guard.check(message)
        emit(TraceEvent("input_guard", "guard", {"verdict": verdict}))
        if verdict == "INJECTION":
            return sessions.finish(s, AgentResult(REFUSAL, status="blocked"))
    if s.pending_handoff == "complaint" and is_affirmative(message):
        result = AGENTS["complaint"](s.handoff_note, ctx)
    else:
        d = router.route(ctx, message)
        emit(TraceEvent("router", "decision", d))
        if d["multiple_issues"] and settings.ENABLE_ORCHESTRATOR:
            result = orchestrator.orchestrate(message, ctx)
        else:
            result = AGENTS["chitchat" if verdict == "OFF_TOPIC" else d["intent"]](message, ctx)
    if settings.GUARDS_ENABLED:
        result = output_guard.check(result, rerun=lambda feedback: rerun_agent(feedback, ctx))
    s.pending_handoff, s.handoff_note = result.handoff, result.handoff_note
    return sessions.finish(s, result)                  # saves messages, token use, handoff
```

`settings.MAX_STEPS` caps the agent calls in one turn, including the output-guard retry and orchestrator workers.

### 5.2 Router (Lab 2B)

- `prompts/router.md`: one line per intent; the **tie-break rule** (classify by what the customer asks us to do, not by everything they mention); `multiple_issues` only for two or more **separate** requests.
- Call `kit.chat(..., model="main", system=ROUTER, schema=ROUTER_SCHEMA)` on the last 4 messages plus the summary.
- Validate `reply.data` (an `intent` in `INTENTS`); retry once; then fall back to chitchat with a clarifying question.
- Run the router set on both models. Use Gemma only if its accuracy is close to Mistral's.

### 5.3 Orchestrator (Lab 2B TODO 3)

```python
def orchestrate(message: str, ctx: TurnContext) -> AgentResult:
    parts = decompose(message)                         # Mistral, JSON list of {intent, text}
    others = [p for p in parts if p["intent"] != "complaint"]
    results = kit.batch(lambda p: AGENTS[p["intent"]](p["text"], ctx), others)
    for p in parts:
        if p["intent"] == "complaint":                 # at most one, run on its own
            results.append(AGENTS["complaint"](p["text"], ctx))
            break
    reply = kit.chat(format_parts(parts, results), model="main", system=SYNTHESISER)
    return AgentResult(reply.text, [e for r in results for e in r.evidence], status=worst_status(results))
```

Each part must be self-contained ("rate it 1 star" becomes "Rate the milk in my last order 1 star"). The synthesiser may not add facts.

### 5.4 Sessions and memory (Lab 2D)

| Function | When | Rule |
|---|---|---|
| `compact(session)` | Every turn | Over `HISTORY_TOKEN_BUDGET`: keep the last 6 messages; summarise the rest with a "what must survive" prompt |
| `recall(user_id, limit=10)` | Session start, into `ctx.memories` | `SELECT kind, content FROM memories WHERE user_id = ? ORDER BY id DESC LIMIT ?` |
| `extract_memories(session)` | `/new` and `/quit` | Mistral, JSON; kinds `allergy`, `language`, `preference` only; never addresses, phone numbers, payment data or other people's names |

### 5.5 Output guard (X3)

1. Find every number in `result.answer`: ₹/Rs amounts, prices, stock counts, minutes, times, percentages.
2. Collect every number in `result.evidence` payloads. Normalise both (₹1,200 = 1200.00).
3. All grounded → pass. Otherwise, first attempt → rerun the agent with "These values are not in any tool result: … Check with tools or remove them." Second failure → safe fallback text.
4. `blocked` results pass straight through. The evals call the same `grounding.py`.

### 5.6 Chat service and CLI

```python
class ChatService:
    def start_session(self, user_id: str) -> str                                  # recall() into the session
    def send(self, session_id: str, message: str) -> Iterator[TraceEvent | str]   # trace events, then the answer
    def end_session(self, session_id: str) -> int                                 # extract_memories → count
    def pending_approvals(self) -> list[dict]                                     # → approvals.pending()
    def decide(self, complaint_id: str, approve: bool, operator: str) -> str      # → approvals.decide(..., notify=sessions.post_notice)
    def stats(self) -> dict                                                       # optional A1–A2
```

| Command | What it does |
|---|---|
| `python -m orchestration.cli chat --user u1` | Interactive chat with the live trace |
| `python -m orchestration.cli operator` | Operator console (second terminal): list, approve, reject |
| `python -m orchestration.cli eval [--guards off]` | Runs `evals/` |
| `python -m orchestration.cli stats` | Optional A1–A2 tables |
| `python -m orchestration.cli health` | Checks the database, the platform and the recordings |

In-chat commands: `/new`, `/user u2`, `/trace on|off`, `/pending`, `/approve <id>`, `/reject <id>`, `/quit`. Print unshown notices before each prompt. Show trace lines live, and the answer only after the output guard.

---

## 6. Interfaces

**You provide:**

| To | What |
|---|---|
| Team 2 | `ctx.memories` filled by `recall()` (e.g. the remembered peanut allergy), plus `ctx.history`, `ctx.summary`, `ctx.budget` |
| Team 3 | `sessions.post_notice(session_id: str, text: str) -> None`, passed as `notify` to `approvals.decide()` |

**You call (stand-ins until the merges):**

| Function | From | Until then |
|---|---|---|
| `assist_agents.query_agent.run(message, ctx) -> AgentResult` | Team 2, Merge 1 | `stubs.query_run` |
| `assist_agents.feedback_agent.run(message, ctx) -> AgentResult` | Team 2, Merge 1 | `stubs.feedback_run` |
| `complaints.flow.run(message, ctx) -> AgentResult` | Team 3, Merge 2 | `stubs.complaint_run` |
| `complaints.input_guard.check(message) -> "OK" \| "INJECTION" \| "OFF_TOPIC"` | Team 3, Merge 2 | `stubs.check` (always `"OK"`) |
| `complaints.approvals.pending() -> list[dict]` | Team 3, Merge 2 | `stubs.pending` (in-memory list) |
| `complaints.approvals.decide(complaint_id, approve, operator, notify) -> str` | Team 3, Merge 2 | `stubs.decide` |

---

## 7. Working on your own

- From Day 1 the CLI runs end to end on `stubs.py`. Make the stubs return realistic `AgentResult`s with evidence, including one with `handoff="complaint"` and one with `status="needs_approval"`.
- Unit-test the workflow with `FakeLLM` (router replies) and the stubs.
- Record the router set once in the window (`LLM_MODE=record`); re-run it offline with `LLM_MODE=replay`.

---

## 8. Acceptance tests

| Test | Passes when |
|---|---|
| Blocked input | An `INJECTION` verdict never reaches an agent and returns `status="blocked"` |
| Off-topic | An `OFF_TOPIC` verdict goes to chitchat (demo #11: "write me a poem" → polite redirect) |
| Handoff | `handoff="complaint"`, then "yes" → the complaint agent receives `handoff_note` |
| Output guard | A number not in the evidence → retried once → then the fallback text |
| Memory (demo #14) | `u1` says "I'm allergic to peanuts", `/new`, asks for a substitute → `ctx.memories` contains the allergy; `u2` sees nothing |
| Limits (demo #16) | A stub that never finishes ends the turn at `MAX_STEPS` with a clean message |
| Multi-request | "milk was leaking, rate it 1 star, and where is my next order?" → one reply covering all three |
| Router eval | Accuracy and false multi-request flags reported for both models |

---

## 9. Day by day

| Day | Work |
|---|---|
| 1 | Smoke test (T1.1); stand-ins (T1.2); workflow skeleton (T1.3); sessions (T1.6); CLI skeleton (T1.10) |
| 2 | Router + router set (T1.4); ChatService + CLI with live trace (T1.10) |
| 3 | Compaction (T1.7); output guard (T1.8); chitchat (T1.9); **Merge 1** at end of day |
| 4 | **Merge 2**; long-term memory (T1.7); operator commands; notices |
| 5 | Orchestrator (T1.5); evals: guards off vs on, Gemma vs Mistral router (T1.11); Day 5 integration |
| 6 | Rehearsal; README; eval report |

---

## 10. Merging

`main` holds your work from Day 2. You run both merges; the incoming team sits with you.

**Ready before Merge 1:**
- [ ] Workflow, stubs, sessions, CLI and router are on `main`; `pytest` green.
- [ ] `AGENTS`, `input_guard` and the approvals module are each referenced in one place, so every swap is one line.

**Schedule:**

| When | Merge | Gate |
|---|---|---|
| End of Day 3 | **Merge 1:** `team2/dev` → `main` | Demo #1–6 pass in the CLI |
| Day 4 | **Merge 2:** `team3/dev` → `main` | Demo #7–10 and #15 pass |
| Day 5 | Everything switched on; evals | Feature freeze: all automated scenarios green |
| Day 6 | Rehearsal, bug fixes only | Demo runs end to end twice |

**Procedure (both merges, inside 11:00–21:00, with the incoming team):**
1. Check the incoming team has done its checklist (in its pack, §10): `main` pulled in, `pytest` green, demo scenarios passing in `replay` mode.
2. Review the PR `teamN/dev` → `main`: `git diff --stat main` shows changes only in that team's folder, its own data files and its tests.
3. Merge it, then swap the stand-ins:
   - **Merge 1:** `stubs.query_run` → `assist_agents.query_agent.run`; `stubs.feedback_run` → `assist_agents.feedback_agent.run`.
   - **Merge 2:** `stubs.complaint_run` → `complaints.flow.run`; the stub guard → `complaints.input_guard`; the stub approvals → `complaints.approvals`, passing `sessions.post_notice` as `notify`.
4. Rebuild from scratch: delete `var/`, run `python -m data.seed` (and `python -m assist_agents.index` from Merge 1 onwards).
5. Run `pytest`, then the merge's demo scenarios live in `python -m orchestration.cli chat` with `LLM_MODE=record`. Commit the new recordings.
6. Tag the result: `git tag merge-1` / `merge-2`.

**If it fails:** fix forward for up to an hour. Otherwise revert (`git revert -m 1 <merge-commit>`), keep the stand-in, and retry the next morning. The other teams keep working either way.

**Day 5 integration (all teams):**
1. Set `ENABLE_ORCHESTRATOR=true` and `GUARDS_ENABLED=true`.
2. Run all demo scenarios (#1–16) and the evals with guards off, then on.
3. Send each failure to the team that owns the agent; fixes come in as small PRs.
4. Feature freeze at the end of the day.

**After the merges:** you own every bug in the wiring between agents: routing, handoff, notices, the output-guard retry.

**Daily rhythm (you run it):** a 10-minute sync with all six at 11:00 (yesterday, today, blockers). Team 1 also spends about an hour a day reviewing Team 2 and Team 3 PRs.
