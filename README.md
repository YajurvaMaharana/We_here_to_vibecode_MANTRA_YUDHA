# Sentinel-Governor: NovaMart AI Support Agent

An autonomous, verification-first customer support engine engineered for the Mantra Yudha Hackathon. Built on the **Propose-Verify-Commit** architecture: AI reasons, backend verifies, database stores truth, tools perform actions, and humans handle escalated exceptions.

---

## What It Is

Sentinel-Governor replaces fragile, text-generating chatbots with an autonomous, verification-first reasoning system. Instead of allowing language models to calculate monetary amounts, look up order statuses from hallucinated memory, or execute actions unchecked, Sentinel-Governor enforces strict boundaries:
- **Language Models Propose**: The LLM suggests conversational phrasing, identifies user intent, and proposes tool calls.
- **Deterministic Code Verifies**: Pure Python functions re-verify every calculation (return deadlines, restocking fees, loyalty tier extensions, refund caps) and enforce customer ownership boundaries.
- **Database Stores Truth**: Ground-truth records in structured JSON/CSV datasets dictate order state, delivery status, and payment flags.
- **Strict Terminal Envelopes**: Every conversation turn terminates in exactly one of four explicit outcomes: `ANSWER`, `ASK`, `ACT`, or `ESCALATE`.

---

## Architecture

Sentinel-Governor operates across a five-layer deterministic execution pipeline:

```
                      CUSTOMER INPUT (Untrusted Data)
                                    │
                                    ▼
                     ┌───────────────────────────────┐
                     │   1. PRE-FILTER GUARDRAILS    │
                     │  (Regex + Lightweight Class)  │
                     └──────────────┬────────────────┘
                                    │
             [Flagged: Injection, Legal Threat, Safety]
                                    │ ──► ESCALATE (0 LLM Calls)
                                    ▼ [Clean]
                     ┌───────────────────────────────┐
                     │      2. CONTEXT PRELOAD       │
                     │  Customer profile, history,   │
                     │    and open support tickets   │
                     └──────────────┬────────────────┘
                                    │
                                    ▼
                     ┌───────────────────────────────┐
   Tool Schemas      │       3. LLM AGENT LOOP       │
  ─────────────────► │  Propose tool calls (max 6)   │ ◄──┐
                     └──────────────┬────────────────┘    │
                                    │ Tool Calls          │ Tool Results
                                    ▼                     │
                     ┌───────────────────────────────┐    │
                     │  4. TOOLS & POLICY ENGINE     │ ───┘
                     │  DB verification, fee calc,   │
                     │  return windows, refund caps  │
                     └──────────────┬────────────────┘
                                    │ Proposed Decision Payload: finalize()
                                    ▼
                     ┌───────────────────────────────┐
                     │       5. POST-VALIDATOR       │
                     │  Sanitizes leaks (driver/OTP) │
                     │   Downgrades unverified ACT   │
                     └──────────────┬────────────────┘
                                    │
                                    ▼
               TERMINAL DECISION: ANSWER | ASK | ACT | ESCALATE
                                    │
                                    ▼
                     ┌───────────────────────────────┐
                     │    AUDITABLE TRACE TELEMETRY  │
                     │   Latency, tokens, tool logs  │
                     └───────────────────────────────┘
```

Detailed architectural specifications and component workflows are documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Setup

Follow these 4 commands to configure and prepare the project environment:

```bash
git clone https://github.com/YajurvaMaharana/We_here_to_vibecode_MANTRA_YUDHA.git
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Initialize your local environment variables:
```bash
cp .env.example .env
```
Ensure `LLM_API_KEY` and `LLM_MODEL` are set in `.env` if executing live LLM turns.

---

## Run

Launch the Streamlit interactive support dashboard and agent trace inspector:

```bash
streamlit run app.py
```

The UI provides customer persona switching across 10 sample profiles, live decision badges (`ANSWER`, `ASK`, `ACT`, `ESCALATE`), risk-flag chips, and expandable trace cards displaying per-step tool execution, latency (ms), and token counts.

---

## Test

Run unit tests across the policy engine, tools envelope, guardrails, and orchestrator:

```bash
pytest -q tests/
```

Run mutation drill tests to verify policy changes flip outcomes without modifying code:

```bash
pytest -q tests/test_mutation.py
```

---

## Eval

Execute the 39-case offline benchmark evaluation harness to audit accuracy across all 13 hidden test categories:

```bash
python -m eval.run_eval --cases eval/cases.json --out eval/report.md
```

Evaluation summaries report per-category scores (`POLICY`, `REFUND_CAP`, `INJECTION`, `AMBIGUITY`, `OTP_DISPUTE`, `SAFETY`) and export structured Markdown reports to GitHub Actions step summaries.

---

## Repository Map

```
We_here_to_vibecode_MANTRA_YUDHA/
├── .github/
│   ├── PULL_REQUEST_TEMPLATE.md     # 4-line pre-merge compliance checklist
│   └── workflows/
│       ├── ci.yml                   # Lint (ruff) + unit tests on PR & push
│       ├── eval.yml                 # Mutation drill + benchmark eval harness
│       └── submission-check.yml     # Validates deliverables, demo, setup
├── agent/
│   ├── __init__.py
│   ├── data_store.py                # In-memory store, mtime auto-reload, runtime writes
│   ├── guardrails.py                # Pre-filter injection/safety regex + post-validator
│   ├── llm.py                       # Provider-agnostic chat wrapper + FakeLLM runner
│   ├── orchestrator.py              # run_turn(): 5-layer execution and decision state
│   ├── policy_engine.py             # Pure deterministic functions (windows, fees, caps)
│   ├── schemas.py                   # Pydantic v2 data models (AgentResult, Session, Trace)
│   └── tools.py                     # Safe tool envelopes returning {"ok", "data", "error"}
├── data/
│   ├── customers.json               # Seed customer records & loyalty tiers
│   ├── orders.json                  # Order history, delivery status, OTP verification
│   ├── policies.json                # Versioned return windows, fee structures, thresholds
│   └── runtime/                     # Transient state (tickets, refunds) - gitignored
├── docs/
│   ├── ARCHITECTURE.md              # System architecture, data flow & layer contracts
│   ├── LIMITATIONS.md               # Honest known failure modes and edge boundaries
│   ├── MODELS.md                    # Model specifications, selection rationale & swap guide
│   └── PROMPT_STRATEGY.md           # Authority hierarchy, finalize schema & 2-layer defense
├── eval/
│   ├── cases.json                   # Golden test cases across 13 evaluation categories
│   └── run_eval.py                  # Evaluation execution harness & report generator
├── prompts/
│   ├── examples.md                  # Few-shot tool use and disambiguation trajectories
│   ├── injection_classifier.md      # Lightweight secondary security classifier prompt
│   └── system_prompt.md             # Core runtime instructions and finalize schema
├── tests/
│   ├── test_guardrails.py           # Pre-filter pattern tests and post-validate downgrades
│   ├── test_mutation.py             # Policy data change mutation drill
│   ├── test_orchestrator.py         # End-to-end turn flows using FakeLLM
│   ├── test_policy.py               # Deterministic window arithmetic & fee caps
│   ├── test_smoke.py                # Baseline test harness verification
│   └── test_tools.py                # Envelope correctness & ownership isolation
├── .env.example                     # Environment template
├── .gitignore                       # Environment, bytecode, venv, and runtime ignore rules
├── app.py                           # Streamlit UI with trace panel and scenario triggers
├── pyproject.toml                   # Ruff configuration (line-length = 100) & project metadata
├── README.md                        # Project documentation and guide
└── requirements.txt                 # Project dependencies
```

---

## Demo Video

Recorded architecture walkthrough and live 7-scene scenario demo:
- **[Demo Video Link](https://youtu.be/placeholder-demo-link)** *(Target duration: 3–5 minutes)*

---

## Models

- **Default Production Model**: `claude-3-5-sonnet-20241022` via Anthropic Python SDK. Selected for native multi-step tool-calling adherence, low latency, and zero hallucinated schema deviations.
- **Offline / CI Model**: `FakeLLM` scripted deterministic harness for reproducible automated testing without external API dependencies.
- **Model Swapping**: Governed by the single environment variable `LLM_MODEL` in `.env`. See [docs/MODELS.md](docs/MODELS.md) for full configuration details.

---

## Known Limitations

For an unvarnished technical list of known boundary failure modes, including multi-lingual colloquialisms, out-of-order logistics database synchronizations, and unfulfilled order modifications, refer to [docs/LIMITATIONS.md](docs/LIMITATIONS.md).
