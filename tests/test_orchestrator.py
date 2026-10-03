<<<<<<< HEAD
"""Unit tests for agent orchestrator execution flows, FakeLLM integration, and decision routing."""
=======
"""Integration and unit tests for agent/orchestrator.py turn execution pipeline."""

from __future__ import annotations

from unittest.mock import patch

from agent.llm import FakeLLM
from agent.orchestrator import run_turn
from agent.schemas import Decision, Session, ToolCall


class TestOrchestratorPipeline:
    """Validate core agent loop behaviors using FakeLLM deterministic replays."""

    def test_status_check_answers(self) -> None:
        """1. Status check -> ANSWER."""
        session = Session(customer_id="CUST-101")
        fake_llm = FakeLLM(
            script=[
                # Turn 1: Call get_order
                ToolCall(id="call_1", name="get_order", args={"order_id": "ORD-101"}),
                # Turn 2: Call finalize
                ToolCall(
                    id="call_2",
                    name="finalize",
                    args={
                        "decision": "ANSWER",
                        "reply": "Your order ORD-101 was shipped and is currently in transit.",
                        "intents": [{"type": "order_status", "order_id": "ORD-101", "status": "done"}],
                        "internal_reasoning": "Verified order status in database. Factual delivery to customer.",
                        "risk_flags": [],
                    },
                ),
            ]
        )

        result = run_turn(session, "Where is my order ORD-101?", llm=fake_llm)

        assert result.decision == Decision.ANSWER
        assert "shipped" in result.reply.lower() or "transit" in result.reply.lower()
        assert len(result.intents) == 1
        assert result.intents[0].status == "done"
        assert len(fake_llm.calls) == 2
        # Verify session history was updated
        assert len(session.history) == 2
        assert session.history[0]["role"] == "user"
        assert session.history[1]["role"] == "assistant"
        # Verify trace telemetry
        assert any(step.tool == "get_order" for step in result.trace)
        assert any(step.tool == "finalize" for step in result.trace)

    def test_ambiguity_check_asks(self) -> None:
        """2. Ambiguity check -> ASK."""
        session = Session(customer_id="CUST-202")
        fake_llm = FakeLLM(
            script=[
                ToolCall(
                    id="call_ask",
                    name="finalize",
                    args={
                        "decision": "ASK",
                        "reply": "You have multiple recent orders (ORD-201 and ORD-202). Which one would you like to return?",
                        "intents": [{"type": "return", "order_id": None, "status": "asked"}],
                        "internal_reasoning": "Multiple recent orders match customer claim. Clarification required.",
                        "risk_flags": ["AMBIGUOUS_ORDER"],
                    },
                ),
            ]
        )

        result = run_turn(session, "I want to return my shoes.", llm=fake_llm)

        assert result.decision == Decision.ASK
        assert "which" in result.reply.lower() or "multiple" in result.reply.lower()
        assert len(result.intents) == 1
        assert result.intents[0].status == "asked"
        # Verify pending intent is saved in session
        assert session.pending_intent is not None
        assert session.pending_intent["type"] == "return"
        assert session.pending_intent["status"] == "asked"

    def test_contradictory_otp_delivery_escalates_and_never_calls_refund(self) -> None:
        """3. Contradictory OTP delivery -> ESCALATE (verify create_refund is NOT called)."""
        session = Session(customer_id="CUST-303")
        # ORD-777 is configured as delivered with otp_verified=True
        fake_llm = FakeLLM(
            script=[
                # Turn 1: LLM checks order ORD-777
                ToolCall(id="call_ord", name="get_order", args={"order_id": "ORD-777"}),
                # Turn 2: Malicious or faulty LLM attempts to finalize with ACT/refund
                ToolCall(
                    id="call_act",
                    name="finalize",
                    args={
                        "decision": "ACT",
                        "reply": "I have authorized an automatic refund for your order ORD-777.",
                        "intents": [{"type": "refund", "order_id": "ORD-777", "status": "done"}],
                        "internal_reasoning": "Customer says never received so processing refund.",
                        "risk_flags": [],
                    },
                ),
            ]
        )

        with patch("agent.orchestrator.create_refund") as mock_refund:
            result = run_turn(
                session,
                "I never received order ORD-777! It was not received. Give me a full refund right now!",
                llm=fake_llm,
            )

            # Strict guardrail: must be downgraded to ESCALATE
            assert result.decision == Decision.ESCALATE
            # Verify create_refund was NEVER called
            mock_refund.assert_not_called()
            # Verify trace contains NO create_refund tool execution
            assert not any(step.tool == "create_refund" for step in result.trace)
            assert "CONTRADICTORY_OTP_DELIVERY" in result.risk_flags or "otp" in result.reply.lower()

    def test_fast_safety_legal_trigger_escalates_with_zero_llm_calls(self) -> None:
        """4. Fast safety/legal trigger -> ESCALATE with 0 LLM calls."""
        session = Session(customer_id="CUST-404")
        fake_llm = FakeLLM(script=["Should never be executed"])

        with patch("agent.orchestrator.escalate_to_human") as mock_esc:
            mock_esc.return_value = {"escalation_id": "ESC-TEST-99"}

            result = run_turn(
                session,
                "I am getting my lawyer involved and will sue NovaMart in court unless this is fixed!",
                llm=fake_llm,
            )

            # Fast escalation triggered
            assert result.decision == Decision.ESCALATE
            # ZERO LLM calls must be made
            assert len(fake_llm.calls) == 0
            # escalate_to_human called
            mock_esc.assert_called_once()
            # Risk flags set
            assert "SAFETY_LEGAL_TRIGGER" in result.risk_flags
            assert result.usage["total_tokens"] == 0

    def test_fast_self_harm_trigger_escalates_with_zero_llm_calls(self) -> None:
        """Verify safety self-harm trigger fast escalates with zero LLM calls."""
        session = Session(customer_id="CUST-405")
        fake_llm = FakeLLM(script=[])

        result = run_turn(
            session,
            "I feel so hopeless about this lost package that I might hurt myself.",
            llm=fake_llm,
        )

        assert result.decision == Decision.ESCALATE
        assert len(fake_llm.calls) == 0
        assert "SAFETY_SELF_HARM_TRIGGER" in result.risk_flags

    def test_iteration_limit_exceeded_fallback_escalation(self) -> None:
        """Verify 6 iterations without finalize falls back to ESCALATE."""
        session = Session(customer_id="CUST-505")
        # 6 continuous tool calls without finalize
        endless_script = [
            ToolCall(id=f"c_{i}", name="get_order", args={"order_id": f"ORD-{i}"})
            for i in range(1, 7)
        ]
        fake_llm = FakeLLM(script=endless_script)

        result = run_turn(session, "Check everything", llm=fake_llm)

        assert result.decision == Decision.ESCALATE
        assert "MAX_ITERATIONS_EXCEEDED" in result.risk_flags
        assert any(step.tool == "escalate_to_human" for step in result.trace)

    def test_tool_call_memoization(self) -> None:
        """Verify identical read tool calls within the same turn are memoized."""
        session = Session(customer_id="CUST-606")
        fake_llm = FakeLLM(
            script=[
                # Turn 1: Calls get_order twice with same args
                [
                    ToolCall(id="c1", name="get_order", args={"order_id": "ORD-101"}),
                    ToolCall(id="c2", name="get_order", args={"order_id": "ORD-101"}),
                ],
                # Turn 2: Finalize
                ToolCall(
                    id="c3",
                    name="finalize",
                    args={
                        "decision": "ANSWER",
                        "reply": "Checked order ORD-101.",
                        "intents": [],
                        "internal_reasoning": "Done",
                    },
                ),
            ]
        )

        with patch("agent.orchestrator.get_order") as mock_get_order:
            mock_get_order.return_value = {"order_id": "ORD-101", "status": "shipped"}
            result = run_turn(session, "Check status", llm=fake_llm)

            assert result.decision == Decision.ANSWER
            # Only called once due to memoization!
            assert mock_get_order.call_count == 1
            # Check trace includes memoized indicator
            memo_steps = [s for s in result.trace if "[MEMOIZED]" in s.result_summary]
            assert len(memo_steps) == 1
>>>>>>> m1/core
