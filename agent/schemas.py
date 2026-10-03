"""Pydantic schemas and data contracts for agent state, tool calls, and decisions."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Decision(str, Enum):
    """Permitted final outcomes for an agent conversation turn.

    Every conversation turn must resolve to exactly one of these states.
    """

    ANSWER = "ANSWER"
    ASK = "ASK"
    ACT = "ACT"
    ESCALATE = "ESCALATE"


class ToolCall(BaseModel):
    """Specification of a tool call emitted by an LLM."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: f"call_{uuid.uuid4().hex[:8]}")
    name: str
    args: dict[str, Any] = Field(default_factory=dict)

    def __init__(
        self,
        id: str | None = None,
        name: str | None = None,
        args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if id is not None:
            kwargs["id"] = id
        if name is not None:
            kwargs["name"] = name
        if args is not None:
            kwargs["args"] = args
        super().__init__(**kwargs)


class ToolResult(BaseModel):
    """Deterministic result returned by a backend tool execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ok: bool
    data: Any = None
    error: str | None = None

    def __init__(
        self,
        ok: bool | None = None,
        data: Any = None,
        error: str | None = None,
        **kwargs: Any,
    ) -> None:
        if ok is not None:
            kwargs["ok"] = ok
        if data is not None or "data" not in kwargs:
            kwargs["data"] = data
        if error is not None:
            kwargs["error"] = error
        super().__init__(**kwargs)


class Intent(BaseModel):
    """Customer intent extracted and tracked across the conversation turn."""

    type: str
    order_id: str | None = None
    status: str  # "done" | "held" | "asked" | "escalated"

    def __init__(
        self,
        type: str | None = None,
        order_id: str | None = None,
        status: str | None = None,
        **kwargs: Any,
    ) -> None:
        if type is not None:
            kwargs["type"] = type
        if order_id is not None or "order_id" in kwargs:
            kwargs["order_id"] = order_id if order_id is not None else kwargs.get("order_id")
        if status is not None:
            kwargs["status"] = status
        super().__init__(**kwargs)


class TraceStep(BaseModel):
    """Audit telemetry record for a single tool call execution step."""

    step: int
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    result_summary: str = ""
    ms: float = 0.0
    tokens: int = 0

    def __init__(
        self,
        step: int | None = None,
        tool: str | None = None,
        args: dict[str, Any] | None = None,
        result_summary: str | None = None,
        ms: float | None = None,
        tokens: int | None = None,
        **kwargs: Any,
    ) -> None:
        if step is not None:
            kwargs["step"] = step
        if tool is not None:
            kwargs["tool"] = tool
        if args is not None:
            kwargs["args"] = args
        if result_summary is not None:
            kwargs["result_summary"] = result_summary
        if ms is not None:
            kwargs["ms"] = ms
        if tokens is not None:
            kwargs["tokens"] = tokens
        super().__init__(**kwargs)


class AgentResult(BaseModel):
    """Final output contract of an agent reasoning turn."""

    decision: Decision
    reply: str
    intents: list[Intent] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)

    def __init__(
        self,
        decision: Decision | str | None = None,
        reply: str | None = None,
        intents: list[Intent] | None = None,
        risk_flags: list[str] | None = None,
        trace: list[TraceStep] | None = None,
        usage: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if decision is not None:
            if isinstance(decision, str):
                decision = Decision(decision)
            kwargs["decision"] = decision
        if reply is not None:
            kwargs["reply"] = reply
        if intents is not None:
            kwargs["intents"] = intents
        if risk_flags is not None:
            kwargs["risk_flags"] = risk_flags
        if trace is not None:
            kwargs["trace"] = trace
        if usage is not None:
            kwargs["usage"] = usage
        super().__init__(**kwargs)


class Session(BaseModel):
    """Multi-turn session state tracking customer context and active ticket."""

    customer_id: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    pending_intent: dict[str, Any] | None = None
    case_state: dict[str, Any] = Field(default_factory=dict)

    def __init__(
        self,
        customer_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        pending_intent: dict[str, Any] | None = None,
        case_state: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if customer_id is not None or "customer_id" in kwargs:
            kwargs["customer_id"] = (
                customer_id if customer_id is not None else kwargs.get("customer_id")
            )
        if history is not None:
            kwargs["history"] = history
        if pending_intent is not None or "pending_intent" in kwargs:
            kwargs["pending_intent"] = (
                pending_intent if pending_intent is not None else kwargs.get("pending_intent")
            )
        if case_state is not None:
            kwargs["case_state"] = case_state
        super().__init__(**kwargs)
