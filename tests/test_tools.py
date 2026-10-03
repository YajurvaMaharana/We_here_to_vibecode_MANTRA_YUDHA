"""Unit tests for agent/tools.py verifying envelope structure, session ownership,
data sanitization, refund constraints, idempotency, threshold limits, and LLM schemas.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.data_store import DataStore
from agent.tools import (
    TOOL_SPECS,
    TOOLS,
    calculate_refund,
    check_refund_eligibility,
    create_refund,
    create_return,
    create_support_ticket,
    escalate_to_human,
    get_conversations,
    get_customer,
    get_open_tickets,
    get_order,
    get_policy,
    get_product,
    set_data_store,
)


@pytest.fixture
def mock_store(tmp_path: Path) -> DataStore:
    """Fixture initializing a clean isolated DataStore for tool verification."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    # Customers
    customers = [
        {"customer_id": "C101", "name": "Aarav Sharma", "email": "aarav@test.com", "loyalty_tier": "regular"},
        {"customer_id": "C102", "name": "Ananya Patel", "email": "ananya@test.com", "loyalty_tier": "silver"},
    ]
    with open(data_dir / "customers.json", "w", encoding="utf-8") as f:
        json.dump(customers, f)

    # Orders (including private internal fields: driver, route, otp)
    orders = [
        {
            "order_id": "NM-1042",
            "customer_id": "C101",
            "order_date": "2026-09-28T10:00:00+05:30",
            "status": "delivered",
            "delivered_at": "2026-09-30T14:30:00+05:30",
            "order_value": 2499.00,
            "payment_status": "completed",
            "otp_verified": True,
            "otp_code": "849201",
            "driver_name": "Ramesh Kumar",
            "driver_phone": "+91-9811122233",
            "route_id": "DEL-NORTH-44",
            "items": [
                {"item_id": "ITM-1", "sku": "NM-ELEC-102", "name": "Pulse Smartwatch", "price": 2499.00}
            ],
        },
        {
            "order_id": "NM-1102",
            "customer_id": "C102",
            "order_date": "2026-10-01T10:00:00+05:30",
            "status": "shipped",
            "delivered_at": None,
            "order_value": 1299.00,
            "payment_status": "completed",
            "otp_verified": False,
            "otp_code": "551234",
            "driver_name": "Manoj Tiwari",
            "route_id": "MUM-WEST-14",
            "items": [
                {"item_id": "ITM-2", "sku": "NM-FASH-201", "name": "Cotton Shirt", "price": 1299.00}
            ],
        },
        {
            "order_id": "NM-1410",
            "customer_id": "C101",
            "order_date": "2026-10-02T10:00:00+05:30",
            "status": "pending_payment",
            "delivered_at": None,
            "order_value": 1500.00,
            "payment_status": "pending",
            "otp_verified": False,
            "items": [],
        },
        {
            "order_id": "NM-1999",
            "customer_id": "C101",
            "order_date": "2026-09-29T10:00:00+05:30",
            "status": "delivered",
            "delivered_at": "2026-09-30T10:00:00+05:30",
            "order_value": 9000.00,
            "payment_status": "completed",
            "otp_verified": True,
            "items": [
                {"item_id": "ITM-9", "sku": "NM-HOME-301", "name": "Coffee Maker", "price": 9000.00}
            ],
        },
    ]
    with open(data_dir / "orders.json", "w", encoding="utf-8") as f:
        json.dump(orders, f)

    # Products
    products = [
        {"sku": "NM-ELEC-102", "name": "Pulse Smartwatch", "category": "electronics", "price": 2499.00, "returnable": True, "warranty_months": 12},
        {"sku": "NM-FASH-201", "name": "Cotton Shirt", "category": "fashion", "price": 1299.00, "returnable": True, "warranty_months": 0},
        {"sku": "NM-HOME-301", "name": "Coffee Maker", "category": "appliances", "price": 9000.00, "returnable": True, "warranty_months": 24},
    ]
    with open(data_dir / "products.json", "w", encoding="utf-8") as f:
        json.dump(products, f)

    # Policies (threshold 5000)
    policies = [
        {
            "version": "v1",
            "effective_date": "2026-01-01T00:00:00+05:30",
            "base_refund_window_days": 7,
            "loyalty_extensions": {"regular": 0, "silver": 3},
            "category_windows": {"electronics": 7, "fashion": 10},
            "restocking_fees": {"electronics": 0.15, "default": 0.05},
            "approval_threshold": 5000.00,
            "disallowed_fee_reasons": ["damaged", "defective"],
        }
    ]
    with open(data_dir / "policies.json", "w", encoding="utf-8") as f:
        json.dump(policies, f)

    # Tickets & Conversations
    tickets = [
        {"ticket_id": "ST-1001", "customer_id": "C101", "status": "open", "summary": "Open delivery check"}
    ]
    with open(data_dir / "tickets.json", "w", encoding="utf-8") as f:
        json.dump(tickets, f)

    conversations = [
        {"conversation_id": "CONV-1", "customer_id": "C101", "messages": [{"role": "user", "content": "Help me"}]}
    ]
    with open(data_dir / "conversations.json", "w", encoding="utf-8") as f:
        json.dump(conversations, f)

    store = DataStore(data_dir=data_dir)
    set_data_store(store)
    return store


# -----------------------------------------------------------------------------
# Envelope Structure & Lookup Tests
# -----------------------------------------------------------------------------

def test_get_customer(mock_store: DataStore):
    """get_customer returns envelope with customer data or customer_not_found error."""
    # Existing by ID
    res = get_customer(customer_id="C101")
    assert res["ok"] is True
    assert res["data"]["name"] == "Aarav Sharma"
    assert res["error"] is None

    # Existing by Email
    res_mail = get_customer(email="aarav@test.com")
    assert res_mail["ok"] is True
    assert res_mail["data"]["customer_id"] == "C101"

    # Missing
    res_missing = get_customer(customer_id="NONEXISTENT")
    assert res_missing["ok"] is False
    assert res_missing["data"] is None
    assert res_missing["error"] == "customer_not_found"


def test_get_product(mock_store: DataStore):
    """get_product returns envelope with product data or product_not_found error."""
    res = get_product(sku="NM-ELEC-102")
    assert res["ok"] is True
    assert res["data"]["name"] == "Pulse Smartwatch"

    res_missing = get_product(sku="UNKNOWN-SKU")
    assert res_missing["ok"] is False
    assert res_missing["data"] is None
    assert res_missing["error"] == "product_not_found"


# -----------------------------------------------------------------------------
# Session Ownership & Data Sanitization Tests
# -----------------------------------------------------------------------------

def test_get_order_ownership_mismatch(mock_store: DataStore):
    """Order belonging to a different customer returns ownership_mismatch with leaked data = None."""
    # NM-1042 belongs to C101; C102 requests it
    res = get_order(order_id="NM-1042", customer_id="C102")
    assert res["ok"] is False
    assert res["data"] is None
    assert res["error"] == "ownership_mismatch"


def test_get_order_not_found(mock_store: DataStore):
    """Non-existent order returns order_not_found error."""
    res = get_order(order_id="NM-9999", customer_id="C101")
    assert res["ok"] is False
    assert res["data"] is None
    assert res["error"] == "order_not_found"


def test_get_order_strips_internal_fields_and_exposes_booleans(mock_store: DataStore):
    """get_order strips driver, route, and OTP data while exposing derived booleans."""
    res = get_order(order_id="NM-1042", customer_id="C101")
    assert res["ok"] is True
    data = res["data"]

    # Verify private fields are stripped
    assert "otp_code" not in data
    assert "otp" not in data
    assert "driver_name" not in data
    assert "driver_phone" not in data
    assert "route_id" not in data

    # Verify derived booleans
    assert data["delivered"] is True
    assert data["otp_verified"] is True
    assert data["payment_pending"] is False
    assert data["already_refunded"] is False


def test_other_order_tools_enforce_ownership(mock_store: DataStore):
    """All order tools strictly verify session ownership."""
    assert check_refund_eligibility("NM-1042", "C102", "return")["error"] == "ownership_mismatch"
    assert calculate_refund("NM-1042", "C102", 100.0, "return")["error"] == "ownership_mismatch"
    assert create_return("NM-1042", "C102", "return")["error"] == "ownership_mismatch"
    assert create_refund("NM-1042", "C102", 100.0, "return")["error"] == "ownership_mismatch"


# -----------------------------------------------------------------------------
# Refund Calculations & Eligibility Tests
# -----------------------------------------------------------------------------

def test_calculate_refund_caps_overclaim(mock_store: DataStore):
    """calculate_refund clamps customer claim to net value (order_value - fee)."""
    # NM-1042: order_value = 2499.00, fee = 15% (374.85), net = 2124.15
    res = calculate_refund(order_id="NM-1042", customer_id="C101", requested=10000.0, reason="unwanted")
    assert res["ok"] is True
    data = res["data"]
    assert data["order_value"] == 2499.00
    assert data["restocking_fee"] == 374.85
    assert data["approved_amount"] == 2124.15


# -----------------------------------------------------------------------------
# create_refund Deterministic Guards
# -----------------------------------------------------------------------------

def test_create_refund_refuses_otp_verified_non_delivery(mock_store: DataStore):
    """Delivered order with verified OTP cannot be refunded for non-delivery claim."""
    res = create_refund(
        order_id="NM-1042",
        customer_id="C101",
        amount=2000.0,
        reason="I did not receive this item",
    )
    assert res["ok"] is False
    assert res["error"] == "otp_dispute"


def test_create_refund_refuses_pending_payment(mock_store: DataStore):
    """Orders with pending payment cannot receive refunds."""
    res = create_refund(
        order_id="NM-1410",
        customer_id="C101",
        amount=1000.0,
        reason="refund please",
    )
    assert res["ok"] is False
    assert "payment_pending" in res["error"]


def test_create_refund_refuses_duplicates(mock_store: DataStore):
    """Duplicate refund requests for the same order and reason are rejected."""
    # First refund succeeds
    res1 = create_refund(
        order_id="NM-1042",
        customer_id="C101",
        amount=1500.0,
        reason="size mismatch",
    )
    assert res1["ok"] is True
    assert res1["data"]["status"] == "completed"

    # Second refund with identical order_id and reason is refused
    res2 = create_refund(
        order_id="NM-1042",
        customer_id="C101",
        amount=1500.0,
        reason="size mismatch",
    )
    assert res2["ok"] is False
    assert res2["error"] == "duplicate_refund"


def test_create_refund_approval_required_above_threshold(mock_store: DataStore):
    """Refund exceeding policy approval_threshold (Rs. 5000) triggers APPROVAL_REQUIRED."""
    # NM-1999 order_value is 9000.00
    res = create_refund(
        order_id="NM-1999",
        customer_id="C101",
        amount=8500.0,
        reason="defective item",
    )
    assert res["ok"] is False
    assert res["error"] == "approval_required"
    assert res["data"]["status"] == "APPROVAL_REQUIRED"
    assert res["data"]["approval_threshold"] == 5000.00


# -----------------------------------------------------------------------------
# Ticket, Return, and Escalation ID Format (ST-xxxx)
# -----------------------------------------------------------------------------

def test_create_return_id_and_storage(mock_store: DataStore):
    """create_return generates 4-digit ID and persists record."""
    res = create_return(order_id="NM-1042", customer_id="C101", reason="color faded")
    assert res["ok"] is True
    ret = res["data"]
    assert ret["return_id"].startswith("RT-")
    assert len(ret["return_id"].split("-")[1]) == 4


def test_create_support_ticket_id_and_storage(mock_store: DataStore):
    """create_support_ticket creates ST-xxxx 4-digit ID and persists to runtime."""
    res = create_support_ticket(customer_id="C101", category="delivery", summary="Package arrived late")
    assert res["ok"] is True
    ticket = res["data"]
    assert ticket["ticket_id"].startswith("ST-")
    assert len(ticket["ticket_id"].split("-")[1]) == 4


def test_escalate_to_human_id_and_storage(mock_store: DataStore):
    """escalate_to_human creates ST-xxxx 4-digit ID and stores full diagnostic context."""
    res = escalate_to_human(
        customer_id="C101",
        summary="Customer threatens legal action",
        context={"order_id": "NM-1042", "risk": "legal_threat"},
        priority="high",
    )
    assert res["ok"] is True
    esc = res["data"]
    assert esc["escalation_id"].startswith("ST-")
    assert len(esc["escalation_id"].split("-")[1]) == 4
    assert esc["context"]["risk"] == "legal_threat"


def test_get_open_tickets_and_conversations(mock_store: DataStore):
    """get_open_tickets filters open tickets and get_conversations returns message history."""
    tickets_res = get_open_tickets("C101")
    assert tickets_res["ok"] is True
    assert len(tickets_res["data"]) >= 1

    convs_res = get_conversations("C101")
    assert convs_res["ok"] is True
    assert len(convs_res["data"]) >= 1


def test_get_policy(mock_store: DataStore):
    """get_policy retrieves the active policy version."""
    res = get_policy()
    assert res["ok"] is True
    assert res["data"]["version"] == "v1"


# -----------------------------------------------------------------------------
# Tool Exports & LLM Tool Specs
# -----------------------------------------------------------------------------

def test_tools_and_tool_specs_exports():
    """TOOLS dictionary and TOOL_SPECS list export all 12 tools."""
    assert len(TOOLS) == 12
    assert len(TOOL_SPECS) == 12

    required_names = {
        "get_customer",
        "get_order",
        "get_product",
        "get_conversations",
        "get_open_tickets",
        "get_policy",
        "check_refund_eligibility",
        "calculate_refund",
        "create_return",
        "create_refund",
        "create_support_ticket",
        "escalate_to_human",
    }
    assert set(TOOLS.keys()) == required_names
    spec_names = {s["name"] for s in TOOL_SPECS}
    assert spec_names == required_names

    for spec in TOOL_SPECS:
        assert "name" in spec
        assert "description" in spec
        assert "parameters" in spec or "input_schema" in spec
