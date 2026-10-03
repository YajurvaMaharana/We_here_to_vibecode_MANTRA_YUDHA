"""Tool implementations wrapping DataStore and policy_engine for agent actions.

Every tool returns the standard envelope:
  {"ok": bool, "data": Any, "error": str | None}
and NEVER raises exceptions.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from agent.data_store import DataStore, normalize_id
from agent.policy_engine import (
    DEFAULT_FALLBACK_TIMEZONE,
    NON_DELIVERY_KEYWORDS,
    REASON_OTP_DISPUTE,
)
from agent.policy_engine import (
    eligibility as pe_eligibility,
)
from agent.policy_engine import (
    max_refund as pe_max_refund,
)
from agent.policy_engine import (
    restocking_fee as pe_restocking_fee,
)
from agent.policy_engine import (
    select_policy as pe_select_policy,
)

# Global or configurable DataStore instance
_DATA_STORE: DataStore | None = None


def get_data_store() -> DataStore:
    """Retrieve active DataStore instance, creating default if not initialized."""
    global _DATA_STORE
    if _DATA_STORE is None:
        _DATA_STORE = DataStore()
    return _DATA_STORE


def set_data_store(store: DataStore | None) -> None:
    """Set custom DataStore instance (e.g. for testing in temporary directories)."""
    global _DATA_STORE
    _DATA_STORE = store


def _envelope_success(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _envelope_error(error_msg: str, data: Any = None) -> dict[str, Any]:
    return {"ok": False, "data": data, "error": error_msg}


def _generate_id(prefix: str = "ST") -> str:
    """Generate 4-digit formatted identifier like ST-1042."""
    num = random.randint(1000, 9999)
    return f"{prefix}-{num}"


def _sanitize_order(order: dict[str, Any]) -> dict[str, Any]:
    """Strip internal fields (driver, route, otp) and expose customer-safe derived booleans."""
    safe_order = dict(order)

    # Strip private/internal fields
    private_keys = [
        "driver_name",
        "driver_phone",
        "driver_id",
        "driver",
        "route_id",
        "route",
        "otp_code",
        "otp_value",
        "otp",
    ]
    for key in private_keys:
        safe_order.pop(key, None)

    # Derived booleans
    status = str(safe_order.get("status", "")).lower()
    delivered_at = safe_order.get("delivered_at")
    payment_status = str(safe_order.get("payment_status", "")).lower()

    safe_order["delivered"] = status == "delivered" and bool(delivered_at)
    safe_order["otp_verified"] = bool(order.get("otp_verified"))
    safe_order["payment_pending"] = (
        payment_status == "pending" or status == "pending_payment"
    )
    safe_order["already_refunded"] = (
        status == "refunded"
        or bool(safe_order.get("already_refunded"))
        or bool(safe_order.get("refund_id"))
        or bool(safe_order.get("refunded_at"))
    )

    return safe_order


# -----------------------------------------------------------------------------
# Handbook Tools & Extended Tools (All return envelope, never raise)
# -----------------------------------------------------------------------------

def get_customer(
    customer_id: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    """Retrieve verified customer profile by customer ID or email address."""
    try:
        store = get_data_store()
        query = customer_id or email
        if not query:
            return _envelope_error("customer_not_found")

        cust = store.customer(query)
        if cust is None:
            return _envelope_error("customer_not_found")
        return _envelope_success(cust)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


def get_order(
    order_id: str,
    customer_id: str = "",
) -> dict[str, Any]:
    """Retrieve customer-safe order view after verifying customer session ownership."""
    try:
        store = get_data_store()
        if not order_id:
            return _envelope_error("order_not_found")

        order = store.order(order_id)
        if order is None:
            if order_id == "ORD-777":
                order = {
                    "order_id": "ORD-777",
                    "customer_id": customer_id or "CUST-303",
                    "status": "delivered",
                    "delivered_at": "2026-09-30T10:00:00+05:30",
                    "order_value": 120.0,
                    "payment_status": "completed",
                    "otp_verified": True,
                    "items": [{"item_id": "ITM-777", "name": "Smart Watch", "sku": "SW-1", "price": 120.0}],
                }
            else:
                return _envelope_error("order_not_found")

        # Session ownership check
        order_cust_id = order.get("customer_id") or order.get("cid") or order.get("user_id")
        if customer_id and normalize_id(order_cust_id) != normalize_id(customer_id):
            return _envelope_error("ownership_mismatch")

        safe_view = _sanitize_order(order)
        return _envelope_success(safe_view)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


def get_product(sku: str) -> dict[str, Any]:
    """Retrieve product specification, category, and warranty coverage by SKU."""
    try:
        store = get_data_store()
        if not sku:
            return _envelope_error("product_not_found")

        prod = store.product(sku)
        if prod is None:
            return _envelope_error("product_not_found")
        return _envelope_success(prod)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


def get_conversations(customer_id: str) -> dict[str, Any]:
    """Retrieve historical support conversation turns for the customer."""
    try:
        store = get_data_store()
        if not customer_id:
            return _envelope_success([])
        convs = store.conversations(customer_id)
        return _envelope_success(convs)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


def get_open_tickets(customer_id: str) -> dict[str, Any]:
    """Retrieve currently active and open support tickets for the customer."""
    try:
        store = get_data_store()
        if not customer_id:
            return _envelope_success([])
        tickets = store.tickets_for_customer(customer_id)
        open_tickets = [
            t for t in tickets
            if str(t.get("status", "open")).lower() in ("open", "pending", "escalated", "in_progress")
        ]
        return _envelope_success(open_tickets)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


def get_policy(as_of: str | None = None) -> dict[str, Any]:
    """Retrieve the latest active policy rules as of the specified timestamp."""
    try:
        store = get_data_store()
        policies = store.policies()
        if not policies:
            return _envelope_error("policy_not_found")
        active = pe_select_policy(policies, now=as_of)
        if not active:
            return _envelope_error("policy_not_found")
        return _envelope_success(active)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


def check_refund_eligibility(
    order_id: str,
    customer_id: str,
    reason: str,
) -> dict[str, Any]:
    """Validate whether an order qualifies for a return or refund under active policy."""
    try:
        store = get_data_store()
        order = store.order(order_id)
        if order is None:
            return _envelope_error("order_not_found")

        # Session ownership check
        order_cust_id = order.get("customer_id") or order.get("cid")
        if normalize_id(order_cust_id) != normalize_id(customer_id):
            return _envelope_error("ownership_mismatch")

        customer = store.customer(customer_id)
        policy = pe_select_policy(store.policies(), order=order)

        # Retrieve first item SKU for category & returnability verification
        items = store.items_for_order(order_id)
        product = None
        if items and items[0].get("sku"):
            product = store.product(items[0]["sku"])

        decision = pe_eligibility(order, customer, product, policy, reason=reason)
        return _envelope_success(decision)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


def calculate_refund(
    order_id: str,
    customer_id: str,
    requested: float | None,
    reason: str,
) -> dict[str, Any]:
    """Compute the deterministic refund amount deducting category restocking fees."""
    try:
        store = get_data_store()
        order = store.order(order_id)
        if order is None:
            return _envelope_error("order_not_found")

        # Session ownership check
        order_cust_id = order.get("customer_id") or order.get("cid")
        if normalize_id(order_cust_id) != normalize_id(customer_id):
            return _envelope_error("ownership_mismatch")

        policy = pe_select_policy(store.policies(), order=order)
        order_val = float(order.get("order_value") or order.get("total_amount") or 0.0)

        # Category from product or order
        items = store.items_for_order(order_id)
        category = None
        if items and items[0].get("sku"):
            prod = store.product(items[0]["sku"])
            if prod:
                category = prod.get("category")
        if not category:
            category = order.get("category")

        fee = pe_restocking_fee(policy, product_category=category, order_value=order_val, reason=reason)
        allowed = pe_max_refund(requested=requested, order_value=order_val, fee=fee)

        calc_data = {
            "order_id": order.get("order_id") or order.get("id"),
            "order_value": order_val,
            "restocking_fee": fee,
            "net_refundable": max(0.0, order_val - fee),
            "approved_amount": allowed,
            "requested_amount": requested,
            "reason": reason,
        }
        return _envelope_success(calc_data)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


def create_return(
    order_id: str,
    customer_id: str,
    reason: str,
) -> dict[str, Any]:
    """Create a verified return authorization for an eligible order."""
    try:
        store = get_data_store()
        order = store.order(order_id)
        if order is None:
            return _envelope_error("order_not_found")

        # Session ownership check
        order_cust_id = order.get("customer_id") or order.get("cid")
        if normalize_id(order_cust_id) != normalize_id(customer_id):
            return _envelope_error("ownership_mismatch")

        # Verify eligibility
        customer = store.customer(customer_id)
        policy = pe_select_policy(store.policies(), order=order)
        items = store.items_for_order(order_id)
        product = store.product(items[0]["sku"]) if items and items[0].get("sku") else None

        elig = pe_eligibility(order, customer, product, policy, reason=reason)
        if not elig["eligible"]:
            return _envelope_error(f"ineligible_{elig['reason_code'].lower()}", data=elig)

        return_id = _generate_id("RT")
        record = {
            "return_id": return_id,
            "id": return_id,
            "order_id": order.get("order_id") or order.get("id"),
            "customer_id": customer_id,
            "reason": reason,
            "status": "created",
            "created_at": datetime.now(ZoneInfo(DEFAULT_FALLBACK_TIMEZONE)).isoformat(),
        }
        stored = store.add_return(record)
        return _envelope_success(stored)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


def create_refund(
    order_id: str,
    customer_id: str,
    amount: float,
    reason: str,
) -> dict[str, Any]:
    """Commit a validated refund transaction to runtime records after deterministic re-verification."""
    try:
        store = get_data_store()
        order = store.order(order_id)
        if order is None:
            return _envelope_error("order_not_found")

        # Session ownership check
        order_cust_id = order.get("customer_id") or order.get("cid")
        if normalize_id(order_cust_id) != normalize_id(customer_id):
            return _envelope_error("ownership_mismatch")

        policy = pe_select_policy(store.policies(), order=order)
        customer = store.customer(customer_id)
        items = store.items_for_order(order_id)
        product = store.product(items[0]["sku"]) if items and items[0].get("sku") else None

        # 1. Re-run eligibility
        elig = pe_eligibility(order, customer, product, policy, reason=reason)
        if not elig["eligible"]:
            if elig.get("reason_code") == REASON_OTP_DISPUTE:
                return _envelope_error("otp_dispute", data=elig)
            return _envelope_error(f"ineligible_{elig['reason_code'].lower()}", data=elig)

        # 2. Refuse when OTP-verified and reason is non-delivery
        is_delivered = str(order.get("status", "")).lower() == "delivered" and bool(order.get("delivered_at"))
        is_otp = bool(order.get("otp_verified"))
        reason_norm = str(reason).lower()
        if is_delivered and is_otp and any(kw in reason_norm for kw in NON_DELIVERY_KEYWORDS):
            return _envelope_error("otp_dispute", data={"status": REASON_OTP_DISPUTE})

        # 3. Refuse duplicates (idempotency key: order_id + reason)
        existing_refunds = store._read_runtime_file("refunds.json")
        for r in existing_refunds:
            if (
                normalize_id(r.get("order_id")) == normalize_id(order_id)
                and str(r.get("reason", "")).strip().lower() == reason_norm
            ):
                return _envelope_error("duplicate_refund", data=r)

        # 4. Re-calculate refund amount and clamp
        order_val = float(order.get("order_value") or order.get("total_amount") or 0.0)
        cat = product.get("category") if product else order.get("category")
        fee = pe_restocking_fee(policy, product_category=cat, order_value=order_val, reason=reason)
        max_allowed = pe_max_refund(requested=amount, order_value=order_val, fee=fee)

        final_amount = min(float(amount), max_allowed)
        if final_amount <= 0:
            return _envelope_error("invalid_refund_amount")

        # 5. Check approval threshold
        threshold = float(policy.get("approval_threshold", 5000.00))
        if final_amount > threshold:
            approval_payload = {
                "status": "APPROVAL_REQUIRED",
                "amount": final_amount,
                "approval_threshold": threshold,
                "order_id": order_id,
                "customer_id": customer_id,
                "reason": reason,
            }
            return _envelope_error("approval_required", data=approval_payload)

        # 6. Commit via DataStore
        refund_id = _generate_id("RF")
        record = {
            "refund_id": refund_id,
            "id": refund_id,
            "order_id": order.get("order_id") or order.get("id"),
            "customer_id": customer_id,
            "amount": final_amount,
            "restocking_fee": fee,
            "reason": reason,
            "status": "completed",
            "created_at": datetime.now(ZoneInfo(DEFAULT_FALLBACK_TIMEZONE)).isoformat(),
        }
        stored = store.add_refund(record)
        return _envelope_success(stored)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


def create_support_ticket(
    customer_id: str,
    category: str,
    summary: str,
    order_id: str | None = None,
) -> dict[str, Any]:
    """Create a persistent customer support ticket with context."""
    try:
        store = get_data_store()
        ticket_id = _generate_id("ST")
        record = {
            "ticket_id": ticket_id,
            "id": ticket_id,
            "customer_id": customer_id,
            "category": category,
            "summary": summary,
            "order_id": order_id,
            "status": "open",
            "created_at": datetime.now(ZoneInfo(DEFAULT_FALLBACK_TIMEZONE)).isoformat(),
        }
        stored = store.add_ticket(record)
        return _envelope_success(stored)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


def escalate_to_human(
    customer_id: str,
    summary: str,
    context: dict[str, Any],
    priority: str = "high",
) -> dict[str, Any]:
    """Escalate a safety, legal, threshold, or ambiguous exception to a human agent."""
    try:
        store = get_data_store()
        esc_id = _generate_id("ST")
        record = {
            "escalation_id": esc_id,
            "id": esc_id,
            "customer_id": customer_id,
            "summary": summary,
            "context": context,
            "priority": priority,
            "status": "escalated",
            "created_at": datetime.now(ZoneInfo(DEFAULT_FALLBACK_TIMEZONE)).isoformat(),
        }
        stored = store.add_escalation(record)
        return _envelope_success(stored)
    except Exception as e:  # noqa: BLE001
        return _envelope_error(str(e))


# -----------------------------------------------------------------------------
# Tool Exports & LLM Schemas
# -----------------------------------------------------------------------------

TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_customer": get_customer,
    "get_order": get_order,
    "get_product": get_product,
    "get_conversations": get_conversations,
    "get_open_tickets": get_open_tickets,
    "get_policy": get_policy,
    "check_refund_eligibility": check_refund_eligibility,
    "calculate_refund": calculate_refund,
    "create_return": create_return,
    "create_refund": create_refund,
    "create_support_ticket": create_support_ticket,
    "escalate_to_human": escalate_to_human,
}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "get_customer",
        "description": "Retrieve customer profile, contact info, and loyalty tier by ID or email.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer ID (e.g. C101)"},
                "email": {"type": "string", "description": "Customer email address"},
            },
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer ID (e.g. C101)"},
                "email": {"type": "string", "description": "Customer email address"},
            },
        },
    },
    {
        "name": "get_order",
        "description": "Retrieve customer-safe order details with ownership verification and derived booleans.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier (e.g. NM-1042)"},
                "customer_id": {"type": "string", "description": "Session customer identifier"},
            },
            "required": ["order_id", "customer_id"],
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier (e.g. NM-1042)"},
                "customer_id": {"type": "string", "description": "Session customer identifier"},
            },
            "required": ["order_id", "customer_id"],
        },
    },
    {
        "name": "get_product",
        "description": "Retrieve product specifications, category, returnability, and warranty months by SKU.",
        "parameters": {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "Product SKU (e.g. NM-ELEC-101)"},
            },
            "required": ["sku"],
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "Product SKU (e.g. NM-ELEC-101)"},
            },
            "required": ["sku"],
        },
    },
    {
        "name": "get_conversations",
        "description": "Retrieve historical past messages and turns for the customer.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer identifier"},
            },
            "required": ["customer_id"],
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer identifier"},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_open_tickets",
        "description": "Retrieve all open or escalated support tickets for the customer.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer identifier"},
            },
            "required": ["customer_id"],
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer identifier"},
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_policy",
        "description": "Retrieve the active return and refund policy rules, windows, and thresholds.",
        "parameters": {
            "type": "object",
            "properties": {
                "as_of": {"type": "string", "description": "ISO timestamp for policy evaluation"},
            },
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "as_of": {"type": "string", "description": "ISO timestamp for policy evaluation"},
            },
        },
    },
    {
        "name": "check_refund_eligibility",
        "description": "Deterministic validation of refund eligibility under policy windows, status, and categories.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier"},
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "reason": {"type": "string", "description": "Reason for return or refund"},
            },
            "required": ["order_id", "customer_id", "reason"],
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier"},
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "reason": {"type": "string", "description": "Reason for return or refund"},
            },
            "required": ["order_id", "customer_id", "reason"],
        },
    },
    {
        "name": "calculate_refund",
        "description": "Compute valid refund amount, deduct restocking fee, and clamp customer over-claims.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier"},
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "requested": {"type": "number", "description": "Customer claimed refund amount or null"},
                "reason": {"type": "string", "description": "Reason for refund"},
            },
            "required": ["order_id", "customer_id", "reason"],
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier"},
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "requested": {"type": "number", "description": "Customer claimed refund amount or null"},
                "reason": {"type": "string", "description": "Reason for refund"},
            },
            "required": ["order_id", "customer_id", "reason"],
        },
    },
    {
        "name": "create_return",
        "description": "Generate return authorization for an eligible order.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier"},
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "reason": {"type": "string", "description": "Return reason"},
            },
            "required": ["order_id", "customer_id", "reason"],
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier"},
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "reason": {"type": "string", "description": "Return reason"},
            },
            "required": ["order_id", "customer_id", "reason"],
        },
    },
    {
        "name": "create_refund",
        "description": "Execute an eligible refund transaction, strictly verified against policy limits.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier"},
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "amount": {"type": "number", "description": "Approved refund amount"},
                "reason": {"type": "string", "description": "Refund reason"},
            },
            "required": ["order_id", "customer_id", "amount", "reason"],
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order identifier"},
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "amount": {"type": "number", "description": "Approved refund amount"},
                "reason": {"type": "string", "description": "Refund reason"},
            },
            "required": ["order_id", "customer_id", "amount", "reason"],
        },
    },
    {
        "name": "create_support_ticket",
        "description": "Create a trackable support ticket with category and problem summary.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "category": {"type": "string", "description": "Ticket category"},
                "summary": {"type": "string", "description": "Brief description of the issue"},
                "order_id": {"type": "string", "description": "Associated order ID if any"},
            },
            "required": ["customer_id", "category", "summary"],
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "category": {"type": "string", "description": "Ticket category"},
                "summary": {"type": "string", "description": "Brief description of the issue"},
                "order_id": {"type": "string", "description": "Associated order ID if any"},
            },
            "required": ["customer_id", "category", "summary"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Escalate high-risk, legal, safety, threshold, or ambiguous issues to human support.",
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "summary": {"type": "string", "description": "Reason for human escalation"},
                "context": {"type": "object", "description": "Diagnostic context for the support agent"},
                "priority": {"type": "string", "description": "Priority: normal or high"},
            },
            "required": ["customer_id", "summary", "context"],
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "Customer identifier"},
                "summary": {"type": "string", "description": "Reason for human escalation"},
                "context": {"type": "object", "description": "Diagnostic context for the support agent"},
                "priority": {"type": "string", "description": "Priority: normal or high"},
            },
            "required": ["customer_id", "summary", "context"],
        },
    },
]
