# Known Technical Limitations & Boundary Failure Modes

This document provides a technical inventory of known failure modes, architectural boundaries, and operational constraints in Sentinel-Governor. Written plainly without promotional language.

---

## 1. Asymmetric Logistics Synchronization
- **Failure Mode**: When third-party courier telemetry has not yet synced to NovaMart's structured database, the agent reports the last verified DB scan.
- **Impact**: If a package was physically handed over 10 minutes ago but the carrier webhook is delayed, `get_order` reports `IN_TRANSIT` rather than `DELIVERED`.
- **Mitigation**: The agent explicitly states the timestamp of the last verified scan and never fabricates real-time driver coordinates or estimated delivery windows.

---

## 2. Ambiguity with Repetitive Purchases
- **Failure Mode**: If a customer repeatedly orders the exact same SKU (e.g., three separate orders of identical headphones over two months) and simply says *"I want to return my headphones"*, the agent cannot infer which order is intended.
- **Impact**: The agent returns `Decision.ASK` with candidate order IDs and dates. If the customer responds ambiguously (e.g., *"the one that broke"*), the agent cannot inspect physical items and must ask again or escalate.
- **Mitigation**: After 2 consecutive ambiguous turns, the turn routes to `Decision.ESCALATE` with a human support ticket rather than looping endlessly.

---

## 3. Strict Address Modification Window
- **Failure Mode**: Customers attempting to reroute shipments that have already entered fulfillment.
- **Impact**: Address changes are programmatically rejected for orders in `DISPATCHED`, `OUT_FOR_DELIVERY`, or `DELIVERED` status.
- **Mitigation**: The agent explains why the change is blocked (carrier handover complete) and provides steps to initiate a return or refuse delivery upon arrival.

---

## 4. Multi-Intent Dependency Blocking
- **Failure Mode**: Simultaneous customer instructions where secondary actions depend on unresolved primary actions (e.g., *"Confirm my phone is delivered, then refund it, and change my address"*).
- **Impact**: The agent executes the status check, holds the refund pending status confirmation, and halts the address update. Customers expecting immediate single-turn resolution of all three requests will receive an intermediate `ASK` status breakdown.
- **Mitigation**: `finalize.intents[]` tracks individual intent states (`done`, `held`, `asked`, `escalated`) so subsequent turns resume seamlessly.

---

## 5. Dialect & Obfuscated Pre-Filter Boundaries
- **Failure Mode**: Unconventional romanized transliterations (complex Hinglish/vernacular colloquialisms) or heavily obfuscated adversarial injections (e.g., Unicode zero-width insertions or phonetic evasion).
- **Impact**: Obfuscated strings may bypass the deterministic regex pre-filter and reach the LLM loop.
- **Mitigation**: Layer 2 system prompt insulation and backend tool schema enforcement isolate the model; however, unhandled phrasing may trigger `Decision.ASK` due to low intent classification confidence.

---

## 6. Context Window Windowing
- **Failure Mode**: Multi-turn support sessions exceeding 6 turns.
- **Impact**: To prevent context bloat, token exhaustion, and attention drift, `Session.history` retains only the most recent 6 conversation turns. Specific details mentioned in Turn 1 (e.g., an alternate phone number) will not be present in working prompt context unless logged to a ticket or database record.
- **Mitigation**: Context preload retrieves persistent ticket notes and customer attributes directly from the database rather than relying on session memory.

---

## 7. Policy Mutation File-System Triggers
- **Failure Mode**: Modifying policy files on operating systems where file modification timestamps (`mtime`) do not update immediately.
- **Impact**: In-memory `DataStore` caches may fail to auto-reload until an explicit file write occurs or the operator clicks `"Reload data"` in the control sidebar.
- **Mitigation**: Explicit `"Reload data"` interface button and test-suite cache-clearing fixtures ensure reliable reloading during demo evaluations.
