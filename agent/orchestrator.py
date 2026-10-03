"""
NovaMart Agent Orchestrator (agent/orchestrator.py)
Coordinates end-to-end multi-turn session state, Authority Hierarchy (L1-L4),
Guardrails pre/post validation, and tool execution.
"""

import os
import sys
import uuid
import time
import csv
from typing import Dict, Any, List, Optional

from agent.guardrails import pre_filter, post_validate
from tools.registry import ToolRegistry


# Global cached database from data/ CSVs
_CACHED_DB: Optional[Dict[str, Any]] = None


def get_shared_database(data_dir: str = "data") -> Dict[str, Any]:
    """Loads and caches the dataset from data/ CSVs."""
    global _CACHED_DB
    if _CACHED_DB is not None:
        return _CACHED_DB

    db: Dict[str, Any] = {
        "customers": {},
        "orders": {},
        "products": {},
        "policies": {
            "Electronics": {
                "category": "Electronics",
                "return_window_days": 7,
                "requires_photo": True,
                "restocking_fee_pct": 0,
                "auto_approval_cap": 1000.00
            },
            "Accessories": {
                "category": "Accessories",
                "return_window_days": 10,
                "requires_photo": False,
                "restocking_fee_pct": 0,
                "auto_approval_cap": 500.00
            },
            "General": {
                "category": "General",
                "return_window_days": 14,
                "requires_photo": True,
                "restocking_fee_pct": 0,
                "auto_approval_cap": 500.00
            }
        },
        "tickets": {},
        "refunds": {},
        "escalations": []
    }

    # Products
    prod_path = os.path.join(data_dir, "products.csv")
    if os.path.exists(prod_path):
        with open(prod_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pid = row.get("product_id")
                if pid:
                    db["products"][pid] = {
                        "product_id": pid,
                        "product_name": row.get("product_name"),
                        "category": row.get("category"),
                        "brand": row.get("brand"),
                        "price": float(row.get("price") or 0),
                        "warranty_months": int(row.get("warranty_months") or 0),
                        "returnable": row.get("returnable", "false").lower() == "true",
                        "replacement_available": row.get("replacement_available", "false").lower() == "true"
                    }

    # Customers
    cust_path = os.path.join(data_dir, "customers.csv")
    if os.path.exists(cust_path):
        with open(cust_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cid = row.get("customer_id")
                if cid:
                    db["customers"][cid] = {
                        "customer_id": cid,
                        "name": f"{row.get('first_name', '')} {row.get('last_name', '')}".strip(),
                        "email": row.get("email"),
                        "phone": row.get("phone"),
                        "loyalty_tier": row.get("loyalty_tier", "bronze"),
                        "trust_score": 90 if row.get("loyalty_tier") in ["gold", "platinum"] else 75,
                        "account_status": row.get("account_status", "active"),
                        "total_orders": int(row.get("total_orders") or 0),
                        "recent_refund_count_30d": 0,
                        "payment_methods": [{"id": "PM-DEFAULT", "type": "upi", "last4": "0000", "is_default": True}]
                    }

    # Order Items
    order_items_map: Dict[str, List[Dict[str, Any]]] = {}
    items_path = os.path.join(data_dir, "order_items.csv")
    if os.path.exists(items_path):
        with open(items_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                oid = row.get("order_id")
                if oid:
                    pid = row.get("product_id")
                    prod_info = db["products"].get(pid, {})
                    item_dict = {
                        "item_id": row.get("order_item_id"),
                        "product_id": pid,
                        "title": prod_info.get("product_name", f"Product {pid}"),
                        "category": prod_info.get("category", "General"),
                        "unit_price": float(row.get("unit_price") or 0),
                        "final_price": float(row.get("final_price") or 0),
                        "quantity": int(row.get("quantity") or 1),
                        "is_returnable": prod_info.get("returnable", True),
                        "return_status": row.get("return_status", "none")
                    }
                    order_items_map.setdefault(oid, []).append(item_dict)

    # Orders
    orders_path = os.path.join(data_dir, "orders.csv")
    if os.path.exists(orders_path):
        with open(orders_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                oid = row.get("order_id")
                if oid:
                    items = order_items_map.get(oid, [])
                    category = items[0]["category"] if items else "General"
                    delivered_date = row.get("actual_delivery_date")
                    delivered_iso = f"{delivered_date}T12:00:00Z" if delivered_date else None
                    otp_verified = row.get("delivery_otp_verified", "").lower() == "true"

                    db["orders"][oid] = {
                        "order_id": oid,
                        "customer_id": row.get("customer_id"),
                        "created_at": f"{row.get('order_date', '')}T00:00:00Z",
                        "order_status": row.get("order_status", "delivered").capitalize(),
                        "payment_status": row.get("payment_status", "paid").capitalize(),
                        "payment_method": row.get("payment_method"),
                        "total_amount": float(row.get("total_amount") or 0),
                        "category": category,
                        "items": items,
                        "delivery": {
                            "status": row.get("delivery_status", "delivered").capitalize(),
                            "carrier": row.get("courier", "SwiftLane"),
                            "tracking_number": row.get("tracking_number"),
                            "delivered_at": delivered_iso,
                            "otp_required": otp_verified,
                            "otp_verified": otp_verified,
                            "shipping_address": {
                                "street": row.get("shipping_address"),
                                "city": row.get("city"),
                                "state": row.get("state")
                            }
                        }
                    }

    _CACHED_DB = db
    return _CACHED_DB


class TurnResult:
    """Represents the structured result of an agent orchestrator turn."""
    def __init__(
        self,
        decision: str,
        customer_response: str,
        tools_called: List[Dict[str, Any]],
        steps_trace: List[Dict[str, Any]],
        audit_trail: Dict[str, Any],
        llm_calls: int = 1,
        tokens: int = 150
    ):
        self.decision = decision
        self.customer_response = customer_response
        self.reply = customer_response
        self.tools_called = tools_called
        self.steps_trace = steps_trace
        self.audit_trail = audit_trail
        self.llm_calls = llm_calls
        self.tokens = tokens

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "customer_response": self.customer_response,
            "reply": self.reply,
            "tools_called": self.tools_called,
            "steps_trace": self.steps_trace,
            "audit_trail": self.audit_trail,
            "llm_calls": self.llm_calls,
            "tokens": self.tokens
        }


class Session:
    """Encapsulates session state for a multi-turn customer interaction."""
    def __init__(self, customer_id: str = "CUST-00001", session_id: Optional[str] = None):
        self.customer_id = customer_id
        self.session_id = session_id or f"SESS-{uuid.uuid4().hex[:8].upper()}"
        self.history: List[Dict[str, Any]] = []
        self.all_tools_called: List[str] = []
        self.total_llm_calls: int = 0
        self.total_tokens: int = 0
        self.turn_count: int = 0

        from core.governor import SentinelGovernor

        # Isolated ToolRegistry with shared DB access
        db = get_shared_database()
        # Create a shallow copy with fresh refunds/escalations tracking
        session_db = {
            "customers": db["customers"],
            "orders": db["orders"],
            "products": db["products"],
            "policies": db["policies"],
            "tickets": {},
            "refunds": {},
            "escalations": []
        }
        self.tool_registry = ToolRegistry(db=session_db)
        self.governor = SentinelGovernor(tool_registry=self.tool_registry)


def run_turn(session: Session, message: Optional[str] = None) -> TurnResult:
    """
    Executes a single turn within the session.
    Flexible signature: accepts run_turn(session, message) or run_turn(message, session).
    """
    if isinstance(message, Session):
        # Swap if arguments were provided as run_turn(message, session)
        session, message = message, session

    if message is None:
        message = ""

    session.turn_count += 1
    t0 = time.time()

    # Step 1: Guardrail Pre-Filter (Authority Hierarchy Level 1)
    pf = pre_filter(message)

    # Estimate LLM calls and tokens for this turn
    # Layer 1 regex = 0 LLM calls; if inconclusive and classifier called = 1 call
    llm_calls_this_turn = 0
    tokens_this_turn = len(message.split()) * 4 + 50  # base token estimate

    if pf.force_escalate:
        # Immediate L1 Interception
        decision = "ESCALATE"
        if pf.safety:
            if any(k in message.lower() for k in ["jeene", "harm", "hurt", "suicide", "life", "mar jaunga"]):
                reply = (
                    "I am deeply concerned about what you are sharing. Please know that you are not alone and help is available. "
                    "Please reach out to the national mental health helpline (KIRAN) at 1800-599-0019 or the iCare helpline. "
                    "We are here for you, and I am escalating this immediately to our dedicated senior support team."
                )
            else:
                reply = (
                    "Your safety is our highest priority. I have immediately escalated this concern to our safety and security team "
                    "for urgent review. A senior officer will be contacting you directly."
                )
        elif pf.legal:
            reply = (
                "I understand the seriousness of your concern regarding legal action or police complaint. "
                "I am escalating your case directly to our Senior Grievance & Legal Compliance Officer for immediate review."
            )
        else:
            reply = "Your request has been escalated to our senior support team for priority assistance."

        tools_called = [{"tool": "escalate_to_human", "args": {"reason": "guardrail_l1_escalate"}}]
        session.all_tools_called.append("escalate_to_human")
        steps_trace = [{
            "step": "L1_GUARDRAIL_INTERCEPT",
            "flags": pf.flags,
            "status": "FORCE_ESCALATE"
        }]
        audit = {
            "decision": decision,
            "flags": pf.flags,
            "session_id": session.session_id,
            "turn": session.turn_count
        }

    else:
        # Prompt Injection handling: if injection without force_escalate, sanitize
        effective_message = pf.cleaned_message if pf.injection and pf.cleaned_message.strip() else message

        # Step 2: SentinelGovernor processing turn (Level 2-4)
        gov_out = session.governor.process_turn(
            raw_customer_message=effective_message,
            customer_id=session.customer_id,
            session_id=session.session_id
        )
        llm_calls_this_turn = 1
        tokens_this_turn = len(effective_message.split()) * 4 + len(gov_out.customer_response.split()) * 4 + 320

        # Step 3: Post-validation
        tool_log = session.tool_registry.execution_log
        post_in = {
            "decision": gov_out.decision,
            "customer_response": gov_out.customer_response,
            "audit_trail": gov_out.audit_trail
        }
        val_out = post_validate(post_in, tool_log, {"session_id": session.session_id, "customer_id": session.customer_id})

        raw_dec = val_out.get("decision", "ANSWER")
        decision = "ACT" if raw_dec == "ANSWER" else raw_dec
        reply = val_out.get("customer_response", "")
        tools_called = list(tool_log)
        for t in tool_log:
            tool_name = t.get("tool") if isinstance(t, dict) else str(t)
            if tool_name and tool_name not in session.all_tools_called:
                session.all_tools_called.append(tool_name)

        steps_trace = gov_out.steps_trace
        audit = gov_out.audit_trail

    session.total_llm_calls += llm_calls_this_turn
    session.total_tokens += tokens_this_turn

    turn_res = TurnResult(
        decision=decision,
        customer_response=reply,
        tools_called=tools_called,
        steps_trace=steps_trace,
        audit_trail=audit,
        llm_calls=llm_calls_this_turn,
        tokens=tokens_this_turn
    )

    session.history.append({
        "turn": session.turn_count,
        "user_message": message,
        "result": turn_res
    })

    return turn_res
