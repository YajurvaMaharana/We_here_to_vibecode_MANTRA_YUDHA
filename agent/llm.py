"""Provider-agnostic tool-calling wrapper, LLM chat client, and FakeLLM test mock."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ConfigDict, Field

from agent.schemas import ToolCall

load_dotenv()

DEFAULT_MODEL = os.getenv("LLM_MODEL", "gemini-1.5-flash")


class LLMResponse(BaseModel):
    """Normalized response contract returned by the LLM client or test fake."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)

    def __init__(
        self,
        text: str | None = None,
        tool_calls: list[ToolCall] | None = None,
        usage: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if text is not None:
            kwargs["text"] = text
        if tool_calls is not None:
            kwargs["tool_calls"] = tool_calls
        if usage is not None:
            kwargs["usage"] = usage
        super().__init__(**kwargs)


class FakeLLM:
    """Mock LLM that replays a scripted list of tool calls and responses deterministically."""

    def __init__(self, script: list[Any] | None = None) -> None:
        self.script: list[Any] = list(script or [])
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        system: str = "",
        messages: list[dict[str, Any]] | None = None,
        tools: list[Callable] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return self.chat(
            system=system,
            messages=messages or [],
            tools=tools,
            model=model,
            **kwargs,
        )

    def chat(
        self,
        system: str = "",
        messages: list[dict[str, Any]] | None = None,
        tools: list[Callable] | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.calls.append(
            {
                "system": system,
                "messages": list(messages or []),
                "tools": tools,
                "model": model,
                "kwargs": kwargs,
            }
        )

        if not self.script:
            raise IndexError("FakeLLM script is empty or exhausted.")

        item = self.script.pop(0)
        return self._normalize_script_item(item)

    @staticmethod
    def _normalize_script_item(item: Any) -> LLMResponse:
        if isinstance(item, LLMResponse):
            return item

        default_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        if isinstance(item, str):
            return LLMResponse(text=item, tool_calls=[], usage=default_usage)

        if isinstance(item, ToolCall):
            return LLMResponse(text="", tool_calls=[item], usage=default_usage)

        if isinstance(item, list):
            calls: list[ToolCall] = []
            for elem in item:
                if isinstance(elem, ToolCall):
                    calls.append(elem)
                elif isinstance(elem, dict):
                    calls.append(ToolCall(**elem))
                else:
                    raise TypeError(f"Unsupported tool call format in script: {type(elem)}")
            return LLMResponse(text="", tool_calls=calls, usage=default_usage)

        if isinstance(item, dict):
            text = item.get("text", "")
            raw_calls = item.get("tool_calls", [])
            calls = []
            for elem in raw_calls:
                if isinstance(elem, ToolCall):
                    calls.append(elem)
                elif isinstance(elem, dict):
                    calls.append(ToolCall(**elem))
                else:
                    raise TypeError(f"Unsupported tool call format in script dict: {type(elem)}")
            usage = item.get("usage", default_usage)
            return LLMResponse(text=text, tool_calls=calls, usage=usage)

        raise TypeError(f"Unsupported FakeLLM script item type: {type(item)}")


def build_tool_specs(funcs: list[Callable]) -> list[Callable]:
    """Pass through Python callables which Gemini SDK natively converts to function declarations."""
    if not funcs:
        return []
    return list(funcs)


def _convert_messages(messages: list[dict[str, Any]]) -> list[types.Content]:
    """Convert standardized conversation messages into Google GenAI Content turns."""
    contents: list[types.Content] = []

    for msg in messages:
        if isinstance(msg, types.Content):
            contents.append(msg)
            continue

        role = msg.get("role", "user")
        target_role = "model" if role in ("assistant", "model") else "user"
        parts: list[types.Part] = []

        if role == "tool" or ("name" in msg and role != "model"):
            name = msg.get("name", "tool_result")
            raw_resp = msg.get("content", {})
            if isinstance(raw_resp, dict):
                resp_dict = raw_resp
            elif hasattr(raw_resp, "model_dump"):
                resp_dict = raw_resp.model_dump()
            elif isinstance(raw_resp, str):
                try:
                    parsed = json.loads(raw_resp)
                    resp_dict = parsed if isinstance(parsed, dict) else {"result": parsed}
                except (ValueError, TypeError, json.JSONDecodeError):
                    resp_dict = {"result": raw_resp}
            else:
                resp_dict = {"result": raw_resp}
            parts.append(types.Part.from_function_response(name=name, response=resp_dict))
        else:
            content_text = msg.get("content")
            if content_text:
                if isinstance(content_text, str):
                    parts.append(types.Part.from_text(text=content_text))
                elif isinstance(content_text, list):
                    for item in content_text:
                        if isinstance(item, str):
                            parts.append(types.Part.from_text(text=item))
                        elif isinstance(item, dict) and item.get("text"):
                            parts.append(types.Part.from_text(text=item["text"]))

            tool_calls = msg.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, ToolCall):
                        parts.append(types.Part.from_function_call(name=tc.name, args=tc.args))
                    elif isinstance(tc, dict):
                        tc_name = tc.get("name") or tc.get("function", {}).get("name", "")
                        tc_args = tc.get("args") or tc.get("function", {}).get("arguments", {})
                        if isinstance(tc_args, str):
                            try:
                                tc_args = json.loads(tc_args)
                            except (ValueError, TypeError, json.JSONDecodeError):
                                tc_args = {"raw": tc_args}
                        parts.append(types.Part.from_function_call(name=tc_name, args=tc_args))

        if not parts:
            continue

        if contents and contents[-1].role == target_role:
            contents[-1].parts.extend(parts)
        else:
            contents.append(types.Content(role=target_role, parts=parts))

    return contents


def _parse_gemini_response(response: Any) -> LLMResponse:
    """Parse Gemini GenerateContentResponse into normalized LLMResponse."""
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if not content:
            continue
        parts = getattr(content, "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                text_parts.append(part_text)

            fc = getattr(part, "function_call", None)
            if fc:
                call_id = getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:8]}"
                call_args = getattr(fc, "args", {}) or {}
                if not isinstance(call_args, dict):
                    try:
                        call_args = dict(call_args)
                    except (ValueError, TypeError):
                        call_args = {"value": call_args}
                tool_calls.append(
                    ToolCall(
                        id=call_id,
                        name=getattr(fc, "name", ""),
                        args=call_args,
                    )
                )

    if not tool_calls:
        top_fcs = getattr(response, "function_calls", None) or []
        for fc in top_fcs:
            call_id = getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:8]}"
            call_args = getattr(fc, "args", {}) or {}
            if not isinstance(call_args, dict):
                try:
                    call_args = dict(call_args)
                except (ValueError, TypeError):
                    call_args = {"value": call_args}
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=getattr(fc, "name", ""),
                    args=call_args,
                )
            )

    extracted_text = "".join(text_parts).strip() if text_parts else ""

    usage: dict[str, Any] = {}
    um = getattr(response, "usage_metadata", None)
    if um:
        usage = {
            "prompt_tokens": getattr(um, "prompt_token_count", 0) or 0,
            "completion_tokens": (
                getattr(um, "candidates_token_count", None)
                or getattr(um, "response_token_count", None)
                or 0
            ),
            "total_tokens": getattr(um, "total_token_count", 0) or 0,
        }
        cached = getattr(um, "cached_content_token_count", None)
        if cached is not None:
            usage["cached_tokens"] = cached

    return LLMResponse(
        text=extracted_text,
        tool_calls=tool_calls,
        usage=usage,
    )


def _is_retryable_error(exc: Exception) -> bool:
    """Determine whether an API or network exception qualifies for retry."""
    if isinstance(exc, httpx.TimeoutException):
        return True

    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        if code == 429 or (code is not None and 500 <= code < 600):
            return True

    msg = str(exc).lower()
    retry_markers = [
        "timeout",
        "timed out",
        "readtimeout",
        "connecttimeout",
        "429",
        "rate limit",
        "resource_exhausted",
        "quota",
        "too many requests",
        "500",
        "502",
        "503",
        "504",
        "internal server error",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "unavailable",
    ]
    return any(marker in msg for marker in retry_markers)


def chat(
    system: str,
    messages: list[dict[str, Any]],
    tools: list[Callable] | None = None,
    model: str | None = None,
    client: genai.Client | None = None,
    _backoff_base: float = 1.0,
) -> LLMResponse:
    """Execute a chat completion turn against Gemini with strictly 0.0 temperature and retries.

    Args:
        system: System instruction prompt enforcing persona and boundaries.
        messages: Conversation turn history formatted as a list of dicts.
        tools: Optional list of Python callables exposed for Gemini function calling.
        model: Model name override (defaults to LLM_MODEL env var or 'gemini-1.5-flash').
        client: Optional pre-configured genai.Client instance (useful for testing/injection).
        _backoff_base: Exponential backoff base delay in seconds.

    Returns:
        LLMResponse containing normalized text, tool calls, and token usage.
    """
    api_key = os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY")
    resolved_model = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL

    if client is None:
        if not api_key:
            raise ValueError(
                "LLM_API_KEY environment variable is not set. Please set LLM_API_KEY in your .env file."
            )
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=60000),
        )

    tool_specs = build_tool_specs(tools) if tools else None

    config = types.GenerateContentConfig(
        temperature=0.0,
        system_instruction=system if system else None,
        tools=tool_specs,
        http_options=types.HttpOptions(timeout=60000),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        if tool_specs
        else None,
    )

    contents = _convert_messages(messages)
    if not contents:
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=" ")])]

    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=resolved_model,
                contents=contents,
                config=config,
            )
            return _parse_gemini_response(response)
        except (errors.APIError, httpx.TimeoutException, Exception) as exc:
            if _is_retryable_error(exc) and attempt < max_retries:
                delay = _backoff_base * (2**attempt)
                time.sleep(delay)
                continue
            raise

    raise RuntimeError("Unexpected termination of LLM retry loop.")
