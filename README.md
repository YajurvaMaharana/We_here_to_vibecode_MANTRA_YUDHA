# Sentinel-Governor: NovaMart AI Support Agent

An autonomous, verification-first customer support engine engineered for the Mantra Yudha Hackathon.

## What it is

Sentinel-Governor replaces fragile text-generating chatbots with an autonomous, verification-first reasoning system. It enforces a strict principle: AI proposes actions, deterministic backend code verifies policies and calculations against structured data, and human agents handle escalated exceptions.

## Architecture

Sentinel-Governor uses a multi-layered reasoning pipeline:
1. **Pre-Filter**: Fast deterministic pattern checks (injection, safety, legal flags) with zero LLM calls on detection.
2. **Context Preload**: Loads verified customer records, past conversation history, and active tickets.
3. **LLM Agent Loop**: Reasoning and tool-use loop proposing actions and decisions.
4. **Tools & Policy Engine**: Pure deterministic validation of windows, caps, eligibility, and ownership.
5. **Post-Validator & Trace**: Guarantees boundary compliance before committing actions and logging full trace telemetry.

```
Customer Message
       │
       ▼
┌──────────────┐
│  Pre-Filter  │ ──(flagged)──► ESCALATE (0 LLM calls)
└──────┬───────┘
       ▼
┌──────────────────┐
│ Context Preload  │
└──────┬───────────┘
       ▼
┌──────────────────┐     Tool Calling     ┌────────────────────────┐
│  LLM Agent Loop  │ ◄──────────────────► │  Tools & Policy Engine │
└──────┬───────────┘                      └────────────────────────┘
       ▼
┌──────────────────┐
│  Post-Validator  │ ──► Commit Action / ANSWER / ASK / ACT / ESCALATE
└──────┬───────────┘
       ▼
┌──────────────────┐
│ Audit Trace Log  │
└──────────────────┘
```

## Setup

Run the following 4 commands to configure your environment:

```bash
git clone https://github.com/YajurvaMaharana/We_here_to_vibecode_MANTRA_YUDHA.git
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
pip install -r requirements.txt
```

Copy the environment configuration template:
```bash
cp .env.example .env
```

## Run

Launch the Streamlit web interface:

```bash
streamlit run app.py
```

## Test

Run unit and integration test suites:

```bash
pytest -q tests/
```

Run policy mutation drill tests:

```bash
pytest -q tests/test_mutation.py
```

## Eval

Execute benchmark evaluation cases against standard scenarios:

```bash
python -m eval.run_eval --cases eval/cases.json --out eval/report.md
```

## Demo video

Walkthrough and architecture demo video:
- [Demo Video Link](https://youtube.com) *(Insert recorded demo URL)*

## Known limitations

- Live tool execution requires active backend database connectivity.
- Policy mutations require hot-reloading dataset files on modification.
- Model rate limits and token limits may apply during multi-turn escalation sequences.
