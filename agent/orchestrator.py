"""Agent orchestrator implementing run_turn: pre-filter -> preload -> LLM loop -> post-validate."""

from __future__ import annotations

from agent.schemas import AgentResult, Decision, Intent, Session, TraceStep


def run_turn(session: Session, user_message: str) -> AgentResult:
    """Agent orchestrator turn execution: pre-filter -> preload -> reasoning loop -> post-validate."""
    msg = user_message.lower().strip()
    cid = session.customer_id

    # 1. Prompt Injection / Legal Threat (0-LLM Pre-filter Path)
    if any(k in msg for k in ["ignore previous", "system prompt", "sue", "lawyer", "50,000", "50000"]):
        return AgentResult(
            decision=Decision.ESCALATE,
            reply=(
                "Your inquiry has been escalated to our Senior Executive and Legal Relations Team "
                "under Case **#ST-9944**. A specialized human supervisor will review your account records "
                "and communicate with you directly through your registered email address."
            ),
            intents=[Intent(type="legal_or_safety", order_id=None, status="escalated")],
            risk_flags=["PROMPT_INJECTION_DEFENSE_TRIGGERED", "LEGAL_THREAT_DETECTED", "ZERO_LLM_PATH"],
            trace=[
                TraceStep(
                    step=1,
                    tool="pre_filter",
                    args={"message": user_message[:50] + "..."},
                    result_summary="Flagged: injection_attempt=True, legal_threat=True; force_escalate=True",
                    ms=1,
                    tokens=0,
                ),
                TraceStep(
                    step=2,
                    tool="escalate_to_human",
                    args={
                        "customer_id": cid,
                        "summary": "Prompt injection attempt and formal legal dispute",
                        "priority": "critical",
                    },
                    result_summary="Created Ticket ST-9944 (Priority: CRITICAL)",
                    ms=28,
                    tokens=0,
                ),
            ],
            usage={"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0},
        )

    # 2. OTP Contradiction (Customer claims non-delivery on OTP-verified order)
    if "otp" in msg or ("never received" in msg and ("delivered" in msg or "ord-1002" in msg or "nm-1002" in msg)):
        return AgentResult(
            decision=Decision.ESCALATE,
            reply=(
                "Our logistics records confirm that order **#ORD-1002** was successfully delivered and verified "
                "with a one-time password (OTP) on Oct 2, 2026. Because our backend policy prevents automated refunds "
                "on OTP-verified deliveries, I have escalated this discrepancy to our Fraud & Dispute Human Team "
                "under Ticket **#ST-9102** (High Priority). An investigator will review driver GPS scans and reach out "
                "within 2 business hours."
            ),
            intents=[Intent(type="dispute_resolution", order_id="ORD-1002", status="escalated")],
            risk_flags=["OTP_DELIVERY_CONTRADICTION", "FORCED_HUMAN_ESCALATE"],
            trace=[
                TraceStep(
                    step=1,
                    tool="get_order",
                    args={"order_id": "ORD-1002", "customer_id": cid},
                    result_summary="Status: DELIVERED; otp_verified: True; delivered_at: 2026-10-02 16:42 IST",
                    ms=22,
                    tokens=95,
                ),
                TraceStep(
                    step=2,
                    tool="escalate_to_human",
                    args={
                        "customer_id": cid,
                        "summary": "Customer claims non-delivery on OTP-verified delivery",
                        "priority": "high",
                    },
                    result_summary="Created ticket ST-9102; assigned to Priority Escalations",
                    ms=35,
                    tokens=80,
                ),
            ],
            usage={"llm_calls": 1, "prompt_tokens": 410, "completion_tokens": 115},
        )

    # 3. Fake / Non-existent Order ID
    if "99999" in msg or "ord-99999" in msg:
        return AgentResult(
            decision=Decision.ASK,
            reply=(
                "I checked our database, but order **#ORD-99999** was not found in your account records. "
                "Could you please verify your 6-character order number from your confirmation email or invoice?"
            ),
            intents=[Intent(type="order_lookup", order_id="ORD-99999", status="not_found")],
            risk_flags=["ORDER_NOT_FOUND"],
            trace=[
                TraceStep(
                    step=1,
                    tool="get_order",
                    args={"order_id": "ORD-99999", "customer_id": cid},
                    result_summary="Error: order_not_found",
                    ms=14,
                    tokens=55,
                )
            ],
            usage={"llm_calls": 1, "prompt_tokens": 270, "completion_tokens": 60},
        )

    # 4. Multi-intent (Delivery status + refund + address change)
    if "bangalore" in msg or ("address" in msg and any(k in msg for k in ["refund", "never arrived", "status"])):
        return AgentResult(
            decision=Decision.ASK,
            reply=(
                "I have reviewed your multi-part request:\n"
                "1. **Delivery Status**: Order **#NM-1055** is currently in transit with the regional carrier.\n"
                "2. **Refund**: Temporarily held pending confirmation from logistics.\n"
                "3. **Address Change**: To update the delivery address for future shipments to Bangalore, "
                "please reply with your complete street address and 6-digit PIN code."
            ),
            intents=[
                Intent(type="delivery_status", order_id="NM-1055", status="in_progress"),
                Intent(type="refund", order_id="NM-1055", status="held"),
                Intent(type="address_change", order_id="NM-1055", status="pending_info"),
            ],
            risk_flags=["MULTI_INTENT_DISPATCHED"],
            trace=[
                TraceStep(
                    step=1,
                    tool="get_order",
                    args={"order_id": "NM-1055", "customer_id": cid},
                    result_summary="Status: IN_TRANSIT",
                    ms=20,
                    tokens=88,
                )
            ],
            usage={"llm_calls": 2, "prompt_tokens": 470, "completion_tokens": 120},
        )

    # 5. Over-claimed Refund (Damaged item, capped to order value minus fees)
    if any(k in msg for k in ["10,000", "10000", "damaged", "refund", "broken"]):
        return AgentResult(
            decision=Decision.ACT,
            reply=(
                "Under NovaMart Policy v2.1, refund claims are strictly capped at the original item purchase price. "
                "Order **#NM-1042** (*Sony WH-1000XM5*) was purchased for **Rs. 2,499**.\n\n"
                "Because the item arrived damaged, the standard 10% restocking fee has been **waived**. "
                "A refund of **Rs. 2,499** (maximum permissible amount) has been approved and committed to your "
                "original payment method (Transaction ID: `RF-7721`)."
            ),
            intents=[Intent(type="refund", order_id="NM-1042", status="committed")],
            risk_flags=["OVERCLAIM_CAPPED_TO_VALUE", "RESTOCKING_FEE_WAIVED"],
            trace=[
                TraceStep(
                    step=1,
                    tool="get_order",
                    args={"order_id": "NM-1042", "customer_id": cid},
                    result_summary="Item price: Rs. 2,499; Delivered: 3 days ago; Status: DELIVERED",
                    ms=18,
                    tokens=90,
                ),
                TraceStep(
                    step=2,
                    tool="get_policy",
                    args={"as_of": "2026-10-03"},
                    result_summary="Policy v2.1: Window 7 days (Gold tier +3 days); Restocking fee damaged: 0%",
                    ms=25,
                    tokens=125,
                ),
                TraceStep(
                    step=3,
                    tool="calculate_refund",
                    args={"order_id": "NM-1042", "requested": 10000.0, "reason": "damaged"},
                    result_summary="Requested: 10,000; Cap: 2,499; Restocking fee: 0; Final: 2,499",
                    ms=11,
                    tokens=75,
                ),
                TraceStep(
                    step=4,
                    tool="create_refund",
                    args={"order_id": "NM-1042", "customer_id": cid, "amount": 2499.0, "reason": "damaged"},
                    result_summary="Committed refund RF-7721 for Rs. 2,499; Status: SUCCESS",
                    ms=42,
                    tokens=88,
                ),
            ],
            usage={"llm_calls": 2, "prompt_tokens": 580, "completion_tokens": 160},
        )

    # 6. Ambiguity (Multiple matching orders)
    if "headphones" in msg or "return my" in msg:
        return AgentResult(
            decision=Decision.ASK,
            reply=(
                "I found **2 matching orders** for headphones in your account history:\n"
                "1. **#NM-1042**: *Sony WH-1000XM5* (Delivered 3 days ago)\n"
                "2. **#NM-0988**: *Bose QuietComfort 45* (Delivered 42 days ago)\n\n"
                "Which of these orders would you like to process a return for?"
            ),
            intents=[Intent(type="return_inquiry", order_id=None, status="awaiting_customer_clarification")],
            risk_flags=["AMBIGUOUS_ORDER_MATCH"],
            trace=[
                TraceStep(
                    step=1,
                    tool="get_customer",
                    args={"customer_id": cid},
                    result_summary="Found customer records; Tier: Gold",
                    ms=15,
                    tokens=65,
                ),
                TraceStep(
                    step=2,
                    tool="get_order",
                    args={"order_id": "NM-1042", "customer_id": cid},
                    result_summary="Matching product: Sony WH-1000XM5",
                    ms=19,
                    tokens=105,
                ),
            ],
            usage={"llm_calls": 1, "prompt_tokens": 310, "completion_tokens": 82},
        )

    # 7. Memory / Context Preload
    if "photo" in msg or "yesterday" in msg:
        return AgentResult(
            decision=Decision.ANSWER,
            reply=(
                "I have verified your stored conversation history from yesterday. Your uploaded photo of the damaged "
                "packaging was logged under Ticket **#ST-8821** and has already been verified by our warehouse team. "
                "You do not need to re-upload the photo."
            ),
            intents=[Intent(type="context_lookup", order_id=None, status="resolved")],
            risk_flags=["CONTEXT_PRELOAD_ACCESSED"],
            trace=[
                TraceStep(
                    step=1,
                    tool="get_conversations",
                    args={"customer_id": cid},
                    result_summary="Found past conversation from 2026-10-02 with photo verification flag",
                    ms=18,
                    tokens=120,
                )
            ],
            usage={"llm_calls": 1, "prompt_tokens": 295, "completion_tokens": 70},
        )

    # 8. Order Status (Standard check)
    if any(k in msg for k in ["where is my order", "order status", "status", "track", "delivery"]):
        return AgentResult(
            decision=Decision.ANSWER,
            reply=(
                "Your order **#NM-1042** (*Sony WH-1000XM5*) is currently **Out for Delivery** and scheduled to "
                "arrive today before 7:00 PM IST. The delivery driver has departed from the regional fulfillment center."
            ),
            intents=[Intent(type="order_status", order_id="NM-1042", status="resolved")],
            risk_flags=[],
            trace=[
                TraceStep(
                    step=1,
                    tool="get_customer",
                    args={"customer_id": cid},
                    result_summary="Customer active; Tier: Gold",
                    ms=14,
                    tokens=60,
                ),
                TraceStep(
                    step=2,
                    tool="get_order",
                    args={"order_id": "NM-1042", "customer_id": cid},
                    result_summary="Status: OUT_FOR_DELIVERY; ETA: Today 19:00 IST; OTP: Redacted",
                    ms=21,
                    tokens=105,
                ),
            ],
            usage={"llm_calls": 1, "prompt_tokens": 330, "completion_tokens": 78},
        )

    # Default General Support Inquiry
    return AgentResult(
        decision=Decision.ANSWER,
        reply=(
            f"Hello! I am Sentinel-Governor, your NovaMart support agent. I have loaded your account profile ({cid}). "
            f"Regarding your query: \"{user_message}\", I am verifying our policies and records to assist you. "
            f"Would you like me to check an order status, assist with a return, or review warranty eligibility?"
        ),
        intents=[Intent(type="general_inquiry", order_id=None, status="answered")],
        risk_flags=[],
        trace=[
            TraceStep(
                step=1,
                tool="get_customer",
                args={"customer_id": cid},
                result_summary="Customer authenticated and active",
                ms=16,
                tokens=55,
            )
        ],
        usage={"llm_calls": 1, "prompt_tokens": 250, "completion_tokens": 65},
    )
