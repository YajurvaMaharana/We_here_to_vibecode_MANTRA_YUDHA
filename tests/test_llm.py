"""Unit tests for agent/schemas.py, FakeLLM, tool result helpers, and agent/llm.py client mechanics."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from google.genai import errors, types

from agent.llm import (
    DEFAULT_MODEL,
    FakeLLM,
    LLMResponse,
    build_tool_response_content,
    build_tool_result_messages,
    build_tool_results,
    build_tool_specs,
    chat,
)
from agent.schemas import (
    FINALIZE_SPEC,
    AgentResult,
    Decision,
    Intent,
    Session,
    ToolCall,
    ToolResult,
    TraceStep,
)


def sample_tool_a(customer_id: str) -> dict[str, str]:
    """Sample tool for testing tool spec conversion."""
    return {"customer_id": customer_id, "status": "active"}


def sample_tool_b(order_id: str, amount: float) -> dict[str, Any]:
    """Sample tool for testing tool spec conversion."""
    return {"order_id": order_id, "amount": amount, "eligible": True}


class TestFakeLLM:
    """Deterministic script playback test cases using FakeLLM with zero network calls."""

    def test_text_response_replay(self) -> None:
        fake = FakeLLM(script=["Hello, welcome to NovaMart! How can I help you today?"])
        res = fake.chat(
            system="You are NovaMart support.",
            messages=[{"role": "user", "content": "Hi"}],
        )

        assert isinstance(res, LLMResponse)
        assert res.text == "Hello, welcome to NovaMart! How can I help you today?"
        assert res.tool_calls == []
        assert res.usage["total_tokens"] == 0
        assert len(fake.calls) == 1
        assert fake.calls[0]["messages"] == [{"role": "user", "content": "Hi"}]

    def test_tool_call_object_replay(self) -> None:
        expected_call = ToolCall(id="call_123", name="get_order", args={"order_id": "ORD-999"})
        fake = FakeLLM(script=[expected_call])

        res = fake.chat(
            system="System prompt",
            messages=[{"role": "user", "content": "Check order ORD-999"}],
        )

        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].id == "call_123"
        assert res.tool_calls[0].name == "get_order"
        assert res.tool_calls[0].args == {"order_id": "ORD-999"}
        assert res.text == ""

    def test_tool_call_dict_replay(self) -> None:
        script_dict = {
            "text": "Checking order details now.",
            "tool_calls": [{"id": "c1", "name": "get_order", "args": {"order_id": "O1"}}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 8, "total_tokens": 23},
        }
        fake = FakeLLM(script=[script_dict])
        res = fake.chat(
            system="Check order",
            messages=[{"role": "user", "content": "Where is my order?"}],
        )

        assert res.text == "Checking order details now."
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].name == "get_order"
        assert res.tool_calls[0].args == {"order_id": "O1"}
        assert res.usage["total_tokens"] == 23

    def test_multi_turn_scripted_agent_flow(self) -> None:
        script = [
            # Turn 1: LLM requests customer profile
            ToolCall(id="tc1", name="get_customer", args={"customer_id": "CUST-1"}),
            # Turn 2: LLM requests order info
            ToolCall(id="tc2", name="get_order", args={"order_id": "ORD-101"}),
            # Turn 3: LLM emits final text reply
            LLMResponse(
                text="Your order ORD-101 was delivered and verified via OTP.",
                tool_calls=[],
                usage={"total_tokens": 85},
            ),
        ]
        fake = FakeLLM(script=script)

        # Step 1
        res1 = fake.chat(
            system="NovaMart Governor",
            messages=[{"role": "user", "content": "Help me"}],
        )
        assert res1.tool_calls[0].name == "get_customer"

        # Step 2
        res2 = fake.chat(
            system="NovaMart Governor",
            messages=[
                {"role": "user", "content": "Help me"},
                {"role": "tool", "name": "get_customer", "content": {"tier": "GOLD"}},
            ],
        )
        assert res2.tool_calls[0].name == "get_order"

        # Step 3
        res3 = fake.chat(
            system="NovaMart Governor",
            messages=[
                {"role": "user", "content": "Help me"},
                {"role": "tool", "name": "get_order", "content": {"status": "DELIVERED"}},
            ],
        )
        assert res3.text == "Your order ORD-101 was delivered and verified via OTP."
        assert res3.tool_calls == []
        assert res3.usage["total_tokens"] == 85
        assert len(fake.calls) == 3

    def test_fake_llm_callable_interface(self) -> None:
        fake = FakeLLM(script=["Callable test response"])
        res = fake(
            system="System",
            messages=[{"role": "user", "content": "Ping"}],
        )
        assert res.text == "Callable test response"

    def test_fake_llm_exhausted_raises_index_error(self) -> None:
        fake = FakeLLM(script=["One reply"])
        fake.chat(messages=[{"role": "user", "content": "1"}])

        with pytest.raises(IndexError, match="script is empty or exhausted"):
            fake.chat(messages=[{"role": "user", "content": "2"}])

    def test_fake_llm_interface_parity_with_chat(self) -> None:
        """FakeLLM must have the same parameter interface as chat() for seamless swapping."""
        chat_params = list(inspect.signature(chat).parameters.keys())
        fake_chat_params = list(inspect.signature(FakeLLM.chat).parameters.keys())[1:]  # strip self
        fake_call_params = list(inspect.signature(FakeLLM.__call__).parameters.keys())[1:]

        assert chat_params == fake_chat_params
        assert chat_params == fake_call_params


class TestToolSpecs:
    """Test tool specifications conversion."""

    def test_build_tool_specs(self) -> None:
        funcs = [sample_tool_a, sample_tool_b]
        specs = build_tool_specs(funcs)
        assert specs == [sample_tool_a, sample_tool_b]
        assert len(specs) == 2

    def test_build_tool_specs_empty(self) -> None:
        assert build_tool_specs([]) == []

    def test_build_tool_specs_with_dict_schema(self) -> None:
        specs = build_tool_specs([FINALIZE_SPEC])
        assert len(specs) == 1
        assert isinstance(specs[0], types.Tool)
        assert len(specs[0].function_declarations) == 1
        assert specs[0].function_declarations[0].name == "finalize"


class TestSchemas:
    """Validate Pydantic v2 schemas: validation, serialization, and constructor semantics."""

    def test_tool_call_positional_and_kwargs(self) -> None:
        tc1 = ToolCall("call_1", "get_order", {"order_id": "ORD-1"})
        assert tc1.id == "call_1"
        assert tc1.name == "get_order"
        assert tc1.args == {"order_id": "ORD-1"}

        tc2 = ToolCall(name="get_product", args={"sku": "SKU-9"})
        assert tc2.id.startswith("call_")
        assert tc2.name == "get_product"

    def test_tool_result_ok_and_error(self) -> None:
        tr_ok = ToolResult(ok=True, data={"refund_amount": 45.0})
        assert tr_ok.ok is True
        assert tr_ok.data == {"refund_amount": 45.0}
        assert tr_ok.error is None

        tr_err = ToolResult(ok=False, data=None, error="Order not found")
        assert tr_err.ok is False
        assert tr_err.error == "Order not found"

    def test_decision_enum_members(self) -> None:
        assert Decision.ANSWER.value == "ANSWER"
        assert Decision.ASK.value == "ASK"
        assert Decision.ACT.value == "ACT"
        assert Decision.ESCALATE.value == "ESCALATE"

        assert Decision("ANSWER") == Decision.ANSWER
        assert Decision("ESCALATE") == Decision.ESCALATE

    def test_intent_schema(self) -> None:
        i1 = Intent(type="refund", order_id="ORD-101", status="done")
        assert i1.type == "refund"
        assert i1.order_id == "ORD-101"
        assert i1.status == "done"

        i2 = Intent(type="inquiry", status="asked")
        assert i2.order_id is None
        assert i2.status == "asked"

    def test_trace_step_schema(self) -> None:
        step = TraceStep(
            step=1,
            tool="check_refund_eligibility",
            args={"order_id": "ORD-1"},
            result_summary="eligible within 14-day window",
            ms=14.2,
            tokens=45,
        )
        assert step.step == 1
        assert step.tool == "check_refund_eligibility"
        assert step.ms == 14.2
        assert step.tokens == 45

    def test_agent_result_schema(self) -> None:
        result = AgentResult(
            decision=Decision.ACT,
            reply="Your refund of $45.00 has been created.",
            intents=[Intent(type="refund", order_id="ORD-1", status="done")],
            risk_flags=["none"],
            trace=[
                TraceStep(
                    step=1,
                    tool="create_refund",
                    args={"amount": 45.0},
                    result_summary="ok",
                    ms=22.0,
                    tokens=30,
                )
            ],
            usage={"total_tokens": 120},
        )
        assert result.decision == Decision.ACT
        assert len(result.intents) == 1
        assert len(result.trace) == 1
        assert result.usage["total_tokens"] == 120

    def test_session_schema(self) -> None:
        session = Session(
            customer_id="CUST-10",
            history=[{"role": "user", "content": "Hi"}],
            pending_intent={"type": "refund"},
            case_state={"verified": True},
        )
        assert session.customer_id == "CUST-10"
        assert len(session.history) == 1
        assert session.case_state["verified"] is True

        empty_session = Session()
        assert empty_session.customer_id is None
        assert empty_session.history == []
        assert empty_session.case_state == {}

    def test_finalize_spec_structure(self) -> None:
        """Validate FINALIZE_SPEC defines all required parameters, types, and enums."""
        assert FINALIZE_SPEC["name"] == "finalize"
        params = FINALIZE_SPEC["parameters"]
        assert params["type"] == "object"

        props = params["properties"]
        assert set(params["required"]) == {
            "decision",
            "intents",
            "reply",
            "internal_reasoning",
            "risk_flags",
        }

        # Decision enum
        assert props["decision"]["type"] == "string"
        assert set(props["decision"]["enum"]) == {"ANSWER", "ASK", "ACT", "ESCALATE"}

        # Intents array schema
        assert props["intents"]["type"] == "array"
        intent_items = props["intents"]["items"]
        assert intent_items["type"] == "object"
        assert set(intent_items["required"]) == {"type", "status"}
        assert intent_items["properties"]["type"]["type"] == "string"
        assert intent_items["properties"]["status"]["type"] == "string"

        # Reply and reasoning
        assert props["reply"]["type"] == "string"
        assert props["internal_reasoning"]["type"] == "string"
        assert props["risk_flags"]["type"] == "array"


class TestMultiToolCallResultHelper:
    """Validate helper building matching tool_result messages for multi-tool turns."""

    def test_build_tool_result_messages_from_list(self) -> None:
        calls = [
            ToolCall(id="call_01", name="get_customer", args={"customer_id": "C-1"}),
            ToolCall(id="call_02", name="get_order", args={"order_id": "ORD-1"}),
        ]
        results = [
            {"customer_id": "C-1", "name": "Aarav"},
            {"order_id": "ORD-1", "status": "DELIVERED"},
        ]

        messages = build_tool_result_messages(calls, results)
        assert len(messages) == 2

        assert messages[0]["role"] == "tool"
        assert messages[0]["tool_call_id"] == "call_01"
        assert messages[0]["name"] == "get_customer"
        assert messages[0]["content"] == {"customer_id": "C-1", "name": "Aarav"}

        assert messages[1]["role"] == "tool"
        assert messages[1]["tool_call_id"] == "call_02"
        assert messages[1]["name"] == "get_order"
        assert messages[1]["content"] == {"order_id": "ORD-1", "status": "DELIVERED"}

    def test_build_tool_result_messages_from_dict_by_id(self) -> None:
        calls = [
            ToolCall(id="c_alpha", name="tool_a", args={}),
            ToolCall(id="c_beta", name="tool_b", args={}),
        ]
        results_map = {
            "c_alpha": {"val": 100},
            "c_beta": {"val": 200},
        }

        messages = build_tool_results(calls, results_map)
        assert len(messages) == 2
        assert messages[0]["tool_call_id"] == "c_alpha"
        assert messages[0]["content"] == {"val": 100}
        assert messages[1]["tool_call_id"] == "c_beta"
        assert messages[1]["content"] == {"val": 200}

    def test_build_tool_result_messages_with_tool_result_objects(self) -> None:
        calls = [
            ToolCall(id="c_res", name="calculate_refund", args={"order_id": "ORD-1"}),
        ]
        results = [
            ToolResult(ok=True, data={"refund_amount": 2499.0}),
        ]

        messages = build_tool_result_messages(calls, results)
        assert len(messages) == 1
        assert messages[0]["content"]["ok"] is True
        assert messages[0]["content"]["data"]["refund_amount"] == 2499.0

    def test_build_tool_response_content(self) -> None:
        calls = [
            ToolCall(id="c1", name="tool_1", args={}),
            ToolCall(id="c2", name="tool_2", args={}),
        ]
        results = [{"status": "ok1"}, {"status": "ok2"}]

        content = build_tool_response_content(calls, results)
        assert isinstance(content, types.Content)
        assert content.role == "user"
        assert len(content.parts) == 2
        assert content.parts[0].function_response.name == "tool_1"
        assert content.parts[0].function_response.id == "c1"
        assert content.parts[1].function_response.name == "tool_2"
        assert content.parts[1].function_response.id == "c2"


class TestChatMechanics:
    """Validate client invocation, parsing, and retry mechanics with mocked Google GenAI client."""

    def test_chat_missing_api_key_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        with pytest.raises(ValueError, match="LLM_API_KEY environment variable is not set"):
            chat(system="Sys", messages=[{"role": "user", "content": "Hi"}], client=None)

    def test_chat_text_parsing_mocked(self) -> None:
        mock_client = MagicMock()
        mock_part = types.Part.from_text(text="I can assist you with your refund.")
        mock_candidate = types.Candidate(content=types.Content(role="model", parts=[mock_part]))
        mock_usage = types.GenerateContentResponseUsageMetadata(
            prompt_token_count=50,
            candidates_token_count=15,
            total_token_count=65,
        )
        mock_response = types.GenerateContentResponse(
            candidates=[mock_candidate],
            usage_metadata=mock_usage,
        )
        mock_client.models.generate_content.return_value = mock_response

        res = chat(
            system="System instruction",
            messages=[{"role": "user", "content": "Help me"}],
            client=mock_client,
            model="gemini-1.5-flash",
        )

        assert res.text == "I can assist you with your refund."
        assert res.tool_calls == []
        assert res.usage["prompt_tokens"] == 50
        assert res.usage["completion_tokens"] == 15
        assert res.usage["total_tokens"] == 65

    def test_chat_function_call_parsing_mocked(self) -> None:
        mock_client = MagicMock()
        mock_fc_part = types.Part.from_function_call(
            name="get_order",
            args={"order_id": "ORD-456"},
        )
        mock_candidate = types.Candidate(content=types.Content(role="model", parts=[mock_fc_part]))
        mock_response = types.GenerateContentResponse(candidates=[mock_candidate])
        mock_client.models.generate_content.return_value = mock_response

        res = chat(
            system="System instruction",
            messages=[{"role": "user", "content": "Where is ORD-456?"}],
            tools=[sample_tool_b],
            client=mock_client,
        )

        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].name == "get_order"
        assert res.tool_calls[0].args == {"order_id": "ORD-456"}

    @patch("time.sleep", return_value=None)
    def test_chat_retry_on_429_exponential_backoff(
        self, mock_sleep: MagicMock
    ) -> None:
        mock_client = MagicMock()
        error_429 = errors.APIError(429, {"message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"})

        mock_part = types.Part.from_text(text="Success after backoff.")
        mock_candidate = types.Candidate(content=types.Content(role="model", parts=[mock_part]))
        success_response = types.GenerateContentResponse(candidates=[mock_candidate])

        mock_client.models.generate_content.side_effect = [
            error_429,
            error_429,
            success_response,
        ]

        res = chat(
            system="System",
            messages=[{"role": "user", "content": "Hi"}],
            client=mock_client,
            _backoff_base=0.1,
        )

        assert res.text == "Success after backoff."
        assert mock_client.models.generate_content.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(0.1)
        mock_sleep.assert_any_call(0.2)

    @patch("time.sleep", return_value=None)
    def test_chat_retry_exhausted_on_500(self, mock_sleep: MagicMock) -> None:
        mock_client = MagicMock()
        error_500 = errors.APIError(500, {"message": "Internal Server Error", "status": "INTERNAL"})

        mock_client.models.generate_content.side_effect = error_500

        with pytest.raises(errors.APIError) as exc_info:
            chat(
                system="System",
                messages=[{"role": "user", "content": "Hi"}],
                client=mock_client,
                _backoff_base=0.01,
            )

        assert exc_info.value.code == 500
        assert mock_client.models.generate_content.call_count == 4
        assert mock_sleep.call_count == 3

    def test_default_model_configured(self) -> None:
        assert DEFAULT_MODEL in ("gemini-1.5-flash", "gemini-flash-lite-latest", "gemini-3.8-flash")

    @patch("time.sleep", return_value=None)
    def test_chat_retry_on_httpx_timeout_exception(self, mock_sleep: MagicMock) -> None:
        mock_client = MagicMock()
        mock_timeout = httpx.ReadTimeout("The read operation timed out")

        mock_part = types.Part.from_text(text="Success after ReadTimeout retry.")
        mock_candidate = types.Candidate(content=types.Content(role="model", parts=[mock_part]))
        success_response = types.GenerateContentResponse(candidates=[mock_candidate])

        mock_client.models.generate_content.side_effect = [mock_timeout, success_response]

        res = chat(
            system="System",
            messages=[{"role": "user", "content": "Ping"}],
            client=mock_client,
            _backoff_base=0.05,
        )

        assert res.text == "Success after ReadTimeout retry."
        assert mock_client.models.generate_content.call_count == 2
        assert mock_sleep.call_count == 1
        mock_sleep.assert_called_once_with(0.05)

    @patch("agent.llm.genai.Client")
    def test_client_initialization_with_60000_timeout(
        self, mock_client_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_API_KEY", "test-key-123")
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_part = types.Part.from_text(text="Init test")
        mock_instance.models.generate_content.return_value = types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[mock_part]))]
        )

        chat(system="Sys", messages=[{"role": "user", "content": "Hi"}], client=None)

        mock_client_cls.assert_called_once()
        _, kwargs = mock_client_cls.call_args
        assert kwargs["api_key"] == "test-key-123"
        assert kwargs["http_options"].timeout == 60000
