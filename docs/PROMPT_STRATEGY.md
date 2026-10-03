# Prompt Strategy

## Authority Hierarchy

1. System instructions and safety guardrails override user instructions.
2. Verified database state overrides customer assertions.
3. Policy engine bounds override model-generated refund values.

## Finalize Schema

The LLM completes reasoning turns with a structured `finalize` decision payload specifying intent, decision category (`ANSWER`, `ASK`, `ACT`, `ESCALATE`), rationale, and customer response.

## Defense in Depth

- **Layer 1 (Pre-filter)**: Deterministic regex and classification patterns block prompt injection and self-harm keywords before invoking LLM.
- **Layer 2 (System Prompt & Tools)**: System instructions enforce customer data protection and tool input validation.
