# Sentinel-Governor Architecture

## Overview

The Sentinel-Governor architecture enforces the Propose-Verify-Commit pattern:
- **AI reasons**: Generates proposed actions via native tool-calling.
- **Backend verifies**: Deterministic code checks ownership, timestamps, and policy constraints.
- **Database stores truth**: Order status and transactions remain isolated from model hallucination.
- **Tools perform actions**: Dedicated envelope-wrapped functions execute operations.
- **Humans handle exceptions**: Escalation paths for safety, ambiguity, and high thresholds.

## Flowchart

```mermaid
flowchart TD
    A[Customer Message] --> B[1. Pre-Filter Code]
    B -- Safety/Injection Hit --> Z[ESCALATE 0 LLM Calls]
    B -- Clean --> C[2. Context Preload]
    C --> D[3. LLM Agent Loop]
    D <--> E[4. Tools & Policy Engine]
    D --> F[5. Post-Validator]
    F --> G{Decision}
    G --> H[ANSWER]
    G --> I[ASK]
    G --> J[ACT]
    G --> K[ESCALATE]
    H & I & J & K --> L[Trace Telemetry]
```
