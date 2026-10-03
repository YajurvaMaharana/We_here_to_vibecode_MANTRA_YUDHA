# AI Model Specifications & Configuration

## 1. Supported Models & Versions

| Model Identifier | Provider / Engine | Primary Use Case |
| :--- | :--- | :--- |
| `claude-3-5-sonnet-20241022` | Anthropic (Native Tool Calling) | **Primary Production Model** – Live reasoning, tool orchestration, and customer replies. |
| `claude-3-haiku-20240307` | Anthropic | **High-Throughput Alternative** – Fast, low-latency execution for high-volume customer queries. |
| `gpt-4o` | OpenAI | **Cross-Provider Fallback** – Verified compatible via provider-agnostic tool schema adapters. |
| `FakeLLM` | In-Memory Deterministic Mock | **Testing & CI Harness** – Offline scripted tool replay allowing deterministic test execution with zero API keys or rate limits. |

---

## 2. Selection Rationale: Claude 3.5 Sonnet

`claude-3-5-sonnet-20241022` was selected as the default model based on three empirical criteria:

1. **Multi-Step Tool-Calling Adherence**:
   Sentinel-Governor frequently requires sequential tool interactions (e.g., `get_order` $\rightarrow$ `get_policy` $\rightarrow$ `calculate_refund` $\rightarrow$ `create_refund` $\rightarrow$ `finalize`). Claude 3.5 Sonnet executes complex, dependency-linked tool calling chains without dropping required fields or looping unnecessarily.

2. **Schema Reliability & Zero Hallucination**:
   The `finalize()` schema requires nested JSON objects with arrays of `Intent` records and explicit `Decision` enums. Sonnet adheres strictly to the schema definition, preventing runtime parsing crashes.

3. **Multi-Intent Separation**:
   In customer messages containing multiple combined intents (e.g., inquiring about a delivery, disputing a charge, and requesting an address change), Sonnet correctly disaggregates requests into discrete sub-intents rather than conflating them into a single action.

---

## 3. How to Swap Models

Sentinel-Governor uses a provider-agnostic abstraction in `agent/llm.py`. Changing models requires zero application code modifications:

### Step 1: Update `.env`
Change the model name in your environment file:
```bash
# To use Claude 3.5 Sonnet (Default)
LLM_MODEL=claude-3-5-sonnet-20241022

# Or switch to Haiku for lower latency
# LLM_MODEL=claude-3-haiku-20240307

# Or switch to OpenAI
# LLM_MODEL=gpt-4o
```

### Step 2: Verify API Credentials
Ensure the corresponding environment key is set in `.env`:
```bash
# For Anthropic models:
LLM_API_KEY=sk-ant-api03-...

# For OpenAI models:
OPENAI_API_KEY=sk-proj-...
```

### Step 3: Run Validation Smoke Test
Verify that the active model successfully loads and invokes tools:
```bash
pytest -q tests/test_smoke.py
```
