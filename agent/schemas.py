"""Pydantic schemas and data contracts for agent state, tool calls, and decisions."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Decision(str, Enum):
    ANSWER = "ANSWER"
    ASK = "ASK"
    ACT = "ACT"
    ESCALATE = "ESCALATE"


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    ok: bool
    data: Any = None
    error: str | None = None


class Intent(BaseModel):
    type: str
    order_id: str | None = None
    status: str = "pending"


class TraceStep(BaseModel):
    step: int
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    result_summary: str
    ms: int = 0
    tokens: int = 0


class AgentResult(BaseModel):
    decision: Decision
    reply: str
    intents: list[Intent] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    usage: dict[str, Any] = Field(
        default_factory=lambda: {"llm_calls": 1, "prompt_tokens": 0, "completion_tokens": 0}
    )


class Session(BaseModel):
    customer_id: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    pending_intent: dict[str, Any] | None = None
    case_state: dict[str, Any] = Field(default_factory=dict)
