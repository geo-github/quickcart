# Group 4 – Agentic Quick-Commerce Chatbot
## High-Level Design

> A short overview. For code contracts, schemas, the agent code pattern and the day-by-day plan, see the low-level design: [Group4_QuickCommerce_Agentic_Design.md](Group4_QuickCommerce_Agentic_Design.md).

---

## 1. What we are building

A command-line chatbot for a quick-commerce store that handles three kinds of request:

| Capability | Example |
|---|---|
| **Queries** | "Where is my order?", "What's the refund policy?", "Anything like X without peanuts?" |
| **Ratings & feedback** | "Is Brand X paneer good?", "Rate my last order 5 stars" |
| **Complaints** | "My order was missing eggs" → verify → refund, operator approval, or escalation |

It shows the agentic building blocks from the workshop: a router, multiple agents, tools, RAG, memory, guardrails and human approval.

**Three ground rules shape the design:**

| Rule | Why | Consequence |
|---|---|---|
| **Use only the lab stack** | Any other package needs explicit approval, and there is no time for that | Python standard library + the packages the labs installed. No LangGraph, Ollama, Streamlit or similar |
| **Use the provided LLM platform** | Mistral and Gemma models are hosted for the training | Nothing runs on our laptops: no GPU, no local models. The platform is available **11:00–21:00 only** |
| **A CLI is enough** | The evaluator confirmed it | No web UI |

---

## 2. Architecture at a glance

```
        ┌──────────────────────────────────────────────┐
        │  1. CLI                                      │
        │  chat · live agent trace · operator commands │
        └──────────────────────┬───────────────────────┘
                               │ function calls
        ┌──────────────────────▼───────────────────────┐
        │  2. Chat service + workflow (plain Python)   │
        │                                              │
        │  Input guard → Router ─┬─ Query agent        │
        │                        ├─ Feedback agent     │
        │                        ├─ Complaint flow     │
        │                        ├─ Chitchat           │
        │                        └─ Orchestrator       │
        │                 → Output guard → reply       │
        └───────────┬──────────────────────┬───────────┘
                    │ tool calls           │ model calls (HTTP API)
        ┌───────────▼─────────────┐  ┌─────▼───────────────────────┐
        │  3. Tools               │  │  4. Provided LLM platform   │
        │  roles · audit log      │  │  Mistral 7B · Gemma 2 2B ·  │
        └─────┬─────────────┬─────┘  │  nomic-embed-text           │
              │             │        └─────────────────────────────┘
   ┌──────────▼───┐  ┌──────▼───────────┐
   │ 5. Database  │  │ 6. Vector store  │
   │ orders,      │  │ policies,        │
   │ products,    │  │ reviews,         │
   │ complaints…  │  │ products         │
   └──────────────┘  └──────────────────┘
```

---

## 3. Components

| # | Component | Responsibility | Technology |
|---|---|---|---|
| 1 | **CLI** | Chat, a live agent trace (which agent and tools ran), operator commands (`/approve`, `/reject`), user switching | Python standard library (`argparse`, `input`, `print`) |
| 2 | **Chat service + workflow** | Runs each message through guard → router → agent → guard; keeps sessions; hands approvals to the complaint flow | Plain Python, written the way the labs wrote agents (no framework) |
| 3 | **Tools** | The only way agents reach data. Inject the user id, check the caller's role, log every write and refused call | Python functions + tool definitions (Lab 2A); optional FastMCP server (Lab 2C) |
| 4 | **LLM platform** | Text generation, tool calling, embeddings | Provided OpenAI-compatible API: **Mistral-7B-Instruct v0.3** (main), **Gemma 2 2B** (light tasks), **nomic-embed-text** (embeddings) |
| 5 | **Database** | Orders, products, allergens, reviews, complaints, refunds, audit log, sessions, long-term memories | SQLite (built into Python) |
| 6 | **Vector store** | Semantic search over policy documents, reviews and product descriptions | ChromaDB 1.5.9 (Lab 2D), with embeddings from the platform |
| 7 | **Policy engine** | Decides refunds with fixed rules (amount limits, late delivery, frequent refunds, safety). **The LLM never decides money** | Plain Python (`Decimal`) |
| 8 | **Guardrails** | Input: blocks prompt injection and off-topic messages. Output: every price, ETA or amount must come from a tool result | Rules + a light-model classifier |
| 9 | **Evaluation** | Router accuracy, groundedness and injection tests, with guards off vs on | pytest (Lab 1D) + small eval scripts |

---

## 4. The agents

Every agent follows the lab setup: **tools as Python functions with a definition dict, a system prompt, and our own agent loop** (Lab 2A), with routing and orchestration as in Lab 2B.

| Agent | Pattern (lab) | What it does | Model | Can use |
|---|---|---|---|---|
| **Router** | Routing gate (2B) | Classifies the message: query, feedback, complaint, chitchat, or several at once | Mistral 7B | No tools |
| **Orchestrator** | Orchestrator–workers (2B) | Splits a multi-request message into parts, runs them in parallel, merges one reply | Mistral 7B | Delegates to the agents below |
| **Query agent** | Agent loop (2A) + RAG (2D) | Order status, product details, substitutes, policy answers with sources | Mistral 7B | Read-only tools |
| **Feedback agent** | Agent loop (2A) + RAG (2D) | Review summaries, collecting ratings; offers a complaint if the rating is low | Mistral 7B | Read tools + save feedback |
| **Complaint flow** | Fixed steps + human approval | Extract → verify against the order → policy decision → refund / operator approval / ticket → reply | Mistral 7B (extraction and wording only) | Called by code, not by the LLM |
| **Chitchat** | Single LLM call | Greetings and off-topic redirects | Gemma 2 2B | No tools |

**Key safety rule:** the refund tool is not available to any LLM agent. Only the complaint flow can call it, and only after the policy engine (or an operator) has approved the refund.

---

## 5. Main flows

**Query:** guard → router → query agent → tools (order / product / policy search) → output guard → reply.

**Complaint:** router → complaint flow → extract details → check the order in the database → policy engine decides:
- **Auto refund** (small amount) → refund issued → confirmation.
- **Needs approval** (large amount or frequent refunds) → saved as **pending** → the customer is told an operator will review → the operator runs `/approve` or `/reject` in the CLI → refund issued (or not) → the customer gets an update message.
- **Escalate** (health/safety) → ticket created → "a person will follow up".
- **Reject** → explanation.

**Multiple requests in one message** ("milk was leaking, rate it 1 star, where is my next order?"): router → orchestrator splits into 3 parts → parts run in parallel → one combined reply.

---

## 6. Cross-cutting concerns

| Concern | How | Technology |
|---|---|---|
| Short-term memory | Conversation saved per session; long chats are summarised (Lab 2D) | SQLite `sessions` / `messages` tables |
| Long-term memory | Preferences (allergies, language) saved at session end and recalled next time, per user only (Lab 2D) | SQLite `memories` table |
| Security | User id injected by our code, role checks, audit log (Lab 2C) | Tool wrapper (`guarded`) |
| Untrusted data | Review and complaint text marked as data, never followed as instructions | Prompt wrapping + tool allow-lists |
| Safety limits | Max turns per agent, token budget per session, tool errors returned instead of crashing (Lab 2A) | Agent loop code |
| Observability | Every step printed live as an agent trace in the CLI | Trace events |
| Platform window (11:00–21:00) | Real model responses are recorded during the window and replayed offline, so development and tests continue | Record-and-replay in the LLM client |

---

## 7. Tech stack summary

| Area | Choice | Source |
|---|---|---|
| Language | Python 3.11+, `venv` + `pip` | Lab 1D |
| LLMs | Provided platform: Mistral-7B-Instruct v0.3, Gemma 2 2B | Training platform |
| LLM client | `llm_kit` (the lab helper) over Python's built-in `urllib` | Labs (`llm_kit`), standard library |
| Embeddings | `nomic-embed-text` on the platform | Training platform |
| Agent orchestration | Plain Python (agent loop, router, orchestrator) | Labs 2A, 2B |
| Tools / MCP | Python functions; optional FastMCP 4.1.1 | Labs 2A, 2C |
| Data | SQLite (built in), ChromaDB 1.5.9 | Labs 2C, 2D |
| Interface | CLI (standard library) | — |
| Tests | pytest | Lab 1D |

> **Note:** the access key and platform URL are confidential. They live only in a git-ignored `.env` file, never in documents or code.

---

## 8. Team split

Each team owns a **vertical slice**: its agents plus the tools, data, prompts and tests those agents need. That way each team can build and test on its own until the merge.

| Team | Members | Owns | Agents |
|---|---|---|---|
| **Team 1: Supervisor & Orchestration** | 2 members | Workflow, chat service + CLI, sessions and memory, output guard, evaluation report, both merges | Router, Orchestrator, Chitchat |
| **Team 2: Query & Feedback Agents** | 2 members | Agent loop, read/feedback tools, product/order/review data, RAG | Query agent, Feedback agent |
| **Team 3: Complaints & Safety** | 2 members | Policy engine, refund/ticket tools, roles + audit log, approvals, input guard, injection tests | Complaint flow |

Each team has its own work pack, with setup steps, tasks and merge steps: [Team 1](Group4_Team1_Supervisor_Orchestration.md) · [Team 2](Group4_Team2_Query_Feedback.md) · [Team 3](Group4_Team3_Complaints_Safety.md).

The small **shared foundation** (shared data formats, the LLM client, the tool wrapper, the seed data) is already built in the `quickcart/` repository, so each team starts its own work on Day 1. The slices are merged on Days 3 and 4.
