"""Smoke test script executing a real LLM call with a dummy tool."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from agent.llm import chat

# Load environment configuration
load_dotenv()


def check_order_status(order_id: str) -> dict[str, Any]:
    """Retrieve order delivery and fulfillment status for a given order ID."""
    return {
        "order_id": order_id,
        "status": "DELIVERED",
        "carrier": "BlueDart",
        "otp_verified": True,
    }


def main() -> None:
    api_key = os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: LLM_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    system_prompt = (
        "You are NovaMart's support assistant. When an order ID is provided, "
        "you MUST call the check_order_status tool to verify it. Do not return direct text."
    )
    messages = [
        {
            "role": "user",
            "content": "Please check the status of my order ORD-55102.",
        }
    ]

    # Execute a real LLM call forcing dummy tool execution
    response = chat(
        system=system_prompt,
        messages=messages,
        tools=[check_order_status],
    )

    if not response.tool_calls:
        print("Warning: Model returned text instead of a tool call:", response.text)
    else:
        for tool_call in response.tool_calls:
            print(f"Tool Name: {tool_call.name}")
            print(f"Tool Args: {tool_call.args}")

    print(f"Usage: {response.usage}")


if __name__ == "__main__":
    main()
