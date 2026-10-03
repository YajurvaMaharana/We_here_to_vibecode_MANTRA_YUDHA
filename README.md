# Sentinel-Governor AI Agent for NovaMart

> **Mantra Yudha Hackathon 2026**  
> *An autonomous, verification-first customer support engine that replaces hallucination-prone chatbots with a constitutional reasoning and verification architecture.*

---

## 1. System Overview & The Iron Principle

> **"AI reasons, backend verifies, database stores truth, tools perform actions, and humans handle exceptions."**

NovaMart's customer support system replaces static chat bubbles with **Sentinel-Governor**: an autonomous agent that enforces an immutable constitutional hierarchy. Accuracy and safety beat speed and friendliness; customer claims are treated as untrusted hypotheses until verified against ground-truth database records.

---

## 2. Authority Hierarchy (Never Violate)

| Level | Layer | Priority | Role & Description |
|:---:|:---|:---:|:---|
| **L1** | **System Prompt** | **Highest** | Immutable constitutional guardrails. Regulates safety, injection defense, authority boundaries, and execution rules. Cannot be overridden. |
| **L2** | **Active Policy** | High | Dynamic category policies fetched via `get_policy()` (return windows, evidence requirements, approval caps, restocking fees). |
| **L3** | **Database / Tool Results** | Authoritative | The absolute ground truth for order state, payment status (`Captured`), carrier telemetry, and OTP delivery verification. |
| **L4** | **Customer Messages** | **Lowest (Untrusted)** | Unverified text enclosed in `<customer_message>`. Treated strictly as claims and requests, never executable instructions. |

---

## 3. Mandatory 8-Step Turn Workflow Pipeline

Every customer turn flows through the 8-step pipeline:

```
[Customer L4 Input]
       │
       ▼
 1. UNDERSTAND ──► Detect distinct intents (order status, refund, return, address change, defect)
       │
       ▼
 2. CONTEXT    ──► Load customer profile, trust score, past tickets & candidate orders
       │
       ▼
 3. VERIFY     ──► Cross-check claim against L3 Ground Truth (get_order, OTP status, payment)
       │
       ▼
 4. POLICY     ──► Retrieve active category policy (get_policy, return window, photo requirement)
       │
       ▼
 5. DECIDE     ──► Select ONE terminal decision: ANSWER | ASK | ACT | ESCALATE
       │
       ▼
 6. ACT        ──► Execute authorized state-changing tools (process_refund, update_shipping_address)
       │
       ▼
 7. CONFIRM    ──► Verify tool receipt and success status
       │
       ▼
 8. FINALIZE   ──► Emit customer response with structured audit trail via finalize()
```

---

## 4. The Four Terminal Decisions

1. **`ANSWER`**: Request is clear and informational, data is verified, zero policy violations. Delivers factual truth.
2. **`ASK`**: Critical information is missing or ambiguous (no order ID with multiple candidates, missing required defect photo). Outputs **exactly ONE** focused question.
3. **`ACT`**: Claims verified against database, eligible under active policy, within auto-approval cap ($100 / ₹5,000), and zero fraud risk. Executes state changes.
4. **`ESCALATE`**: High-risk trigger (OTP-verified delivery dispute, amount > auto cap, repeated refund velocity, legal threats, account mismatch). Hands off to human specialists with a complete audit payload.

> **Default Rule**: Default is NOT to act.  
> `Unsure between ACT and ASK` ➔ `ASK`  
> `Unsure between ACT and ESCALATE` ➔ `ESCALATE`

---

## 5. Repository Structure & Milestone Branches

- `m1/core`: Core reasoning engine, data models, state machine, threat analyzer, claim verifier (`core/`)
- `m2/tools`: Structured tool registry, in-memory mock database with OTP telemetry (`tools/`)
- `m3/prompts`: Constitutional system prompt, prompt specs, few-shot traces, injection defense protocol (`prompts/`)
- `m4/ui`: Split-screen Customer Support Portal & Live Governor Telemetry Inspector (`ui/`)

```
We_here_to_vibecode_MANTRA_YUDHA/
├── core/
│   ├── governor.py          # 8-step SentinelGovernor engine & decision router
│   ├── guardrails.py        # L1 prompt injection and threat detector
│   ├── models.py            # Typed dataclass schemas (Orders, Audits, Claims)
│   └── verifier.py          # Truth vs Claim matrix cross-referencing engine
├── tools/
│   ├── db.py                # Mock database (customers, orders, OTP telemetry, policies)
│   └── registry.py          # 9 tools (get_order, get_policy, process_refund, finalize, etc.)
├── prompts/
│   ├── system_prompt.md     # Full NovaMart constitutional system prompt
│   ├── prompt_spec.json     # Machine-readable prompt and authority specification
│   ├── few_shot_examples.json # Comprehensive 8-step turn traces for each decision
│   └── injection_defense.md # Security analysis & jailbreak mitigation protocol
├── ui/
│   ├── index.html           # Dual-pane UI (Chat Portal + Live Telemetry Inspector)
│   ├── index.css            # Custom dark-mode design system with radiant badges
│   └── app.js               # Client controller with 7 judge demo scenarios
├── tests/
│   └── test_governor.py     # 11 unit tests verifying decisions, OTP, caps & injection
├── server.py                # REST API server & static UI host (Python standard library)
└── README.md
```

---

## 6. Getting Started & Running Locally

### 1. Run Unit Tests
```bash
python -m unittest tests/test_governor.py
```
*(11 tests passing: covers ACT, ESCALATE, ASK, ANSWER, OTP mismatch, prompt injection, cap limit, photo requirements, and account ownership).*

### 2. Launch the Web UI & Telemetry Inspector
```bash
python server.py
```
Open your browser to: **`http://localhost:8080`**

### 3. Demo Scenarios Included in UI
1. **Return in Policy (ACT)**: Sarah Jenkins returns headphones with verified defect photo. Net refund ($79.99) dispatched.
2. **OTP Delivery Scam (ESCALATE)**: David Miller claims package never arrived, but delivery was verified with OTP code at door. Escalate to fraud investigation.
3. **Missing Order ID (ASK)**: Elena Rostova requests address change without order ID. Candidate orders listed, 1 question asked.
4. **Prompt Injection Attack (DEFEND)**: Attacker attempts root override and prompt leakage. Defended under L1, zero leak.
5. **High-Value Item > $100 Cap (ESCALATE)**: $650 damaged TV exceeds autonomous threshold. Forwarded to senior manager.
6. **Order Tracking (ANSWER)**: Real-time courier status and ETA delivered from ground-truth DB.
7. **Expired Return Window (ANSWER)**: 25-day return request denied under 14-day category policy.
