"""Terminal chat loop for Sentinel-Governor NovaMart AI Support Agent."""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.orchestrator import run_turn
from agent.schemas import Session


def main() -> None:
    print("=" * 60)
    print("NovaMart Sentinel-Governor CLI Chat")
    print("=" * 60)

    try:
        raw_cust = input("Enter Customer ID [default: CUST-001]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
        return

    customer_id = raw_cust or "CUST-001"
    session = Session(customer_id=customer_id)
    print(f"Session initialized for customer: {customer_id}")
    print("Type your message below. Type 'exit' or 'quit' to end.\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("\nEnding conversation session. Goodbye!")
                break

            result = run_turn(session, user_input)

            print(f"\n[Decision]: {result.decision.value}")
            print(f"[Reply]: {result.reply}")
            if result.risk_flags:
                print(f"[Risk Flags]: {', '.join(result.risk_flags)}")
            if result.intents:
                intents_str = ", ".join(f"{i.type}:{i.status}" for i in result.intents)
                print(f"[Intents]: {intents_str}")

            print("\n[Execution Trace]:")
            for step in result.trace:
                summary = (
                    step.result_summary[:80] + "..."
                    if len(step.result_summary) > 80
                    else step.result_summary
                )
                print(f"  Step {step.step}: {step.tool}({step.args}) -> {summary} ({step.ms:.1f}ms)")
            print("-" * 60 + "\n")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting chat loop.")
            break


if __name__ == "__main__":
    main()
