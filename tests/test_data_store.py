"""Unit tests for agent/data_store.py covering normalized IDs, safe missing returns,
runtime append isolation, CSV/JSON loading, and automatic hot-reload on mtime change.
"""

from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path

import pytest

from agent.data_store import DataStore, normalize_email, normalize_id


@pytest.fixture
def temp_store(tmp_path: Path) -> DataStore:
    """Fixture providing a fresh DataStore backed by a temporary directory with test datasets."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    # 1. Customers JSON
    customers = [
        {"customer_id": "C101", "name": "Aarav Sharma", "email": "aarav.sharma@example.com", "loyalty_tier": "regular"},
        {"customer_id": "C-102", "name": "Ananya Patel", "email": "ananya.patel@example.com", "loyalty_tier": "silver"},
    ]
    with open(data_dir / "customers.json", "w", encoding="utf-8") as f:
        json.dump(customers, f)

    # 2. Orders JSON (with embedded items)
    orders = [
        {
            "order_id": "NM-1042",
            "customer_id": "C101",
            "order_value": 2499.0,
            "status": "delivered",
            "items": [
                {"item_id": "ITM-1", "sku": "NM-ELEC-102", "name": "Pulse Smartwatch", "quantity": 1, "price": 2499.0}
            ],
        },
        {
            "order_id": "NM-1101",
            "customer_id": "C-102",
            "order_value": 4999.0,
            "status": "delivered",
            "items": [
                {"item_id": "ITM-2", "sku": "NM-ELEC-101", "name": "ANC Headphones", "quantity": 1, "price": 4999.0}
            ],
        },
    ]
    with open(data_dir / "orders.json", "w", encoding="utf-8") as f:
        json.dump(orders, f)

    # 3. Products JSON
    products = [
        {"sku": "NM-ELEC-101", "name": "ANC Headphones", "category": "electronics", "price": 4999.0, "warranty_months": 12},
        {"sku": "NM-ELEC-102", "name": "Pulse Smartwatch", "category": "electronics", "price": 2499.0, "warranty_months": 12},
    ]
    with open(data_dir / "products.json", "w", encoding="utf-8") as f:
        json.dump(products, f)

    # 4. Policies JSON
    policies = [
        {"version": "v1", "base_refund_window_days": 7, "approval_threshold": 5000.0},
        {"version": "v2", "base_refund_window_days": 10, "approval_threshold": 7500.0},
    ]
    with open(data_dir / "policies.json", "w", encoding="utf-8") as f:
        json.dump(policies, f)

    # 5. Conversations JSON
    conversations = [
        {"conversation_id": "CONV-1", "customer_id": "C101", "messages": [{"role": "user", "content": "Where is my order?"}]}
    ]
    with open(data_dir / "conversations.json", "w", encoding="utf-8") as f:
        json.dump(conversations, f)

    # 6. Tickets JSON
    tickets = [
        {"ticket_id": "ST-1001", "customer_id": "C101", "status": "closed", "summary": "Delivery check"}
    ]
    with open(data_dir / "tickets.json", "w", encoding="utf-8") as f:
        json.dump(tickets, f)

    return DataStore(data_dir=data_dir)


# -----------------------------------------------------------------------------
# ID Normalization Tests
# -----------------------------------------------------------------------------

def test_normalize_id_treats_hyphens_as_equal():
    """Ensure NM1042, NM-1042, and variants normalize to the exact same key."""
    assert normalize_id("NM1042") == "NM1042"
    assert normalize_id("NM-1042") == "NM1042"
    assert normalize_id("nm-1042") == "NM1042"
    assert normalize_id("  nm-1042  ") == "NM1042"
    assert normalize_id("NM_1042") == "NM1042"
    assert normalize_id("C-102") == "C102"
    assert normalize_id("c102") == "C102"


def test_normalize_id_handles_none_and_empty():
    """Ensure None and empty inputs return empty string and never raise."""
    assert normalize_id(None) == ""
    assert normalize_id("") == ""
    assert normalize_id("   ") == ""


def test_normalize_email():
    """Ensure email addresses are stripped and lowercased."""
    assert normalize_email(" Aarav.Sharma@Example.COM ") == "aarav.sharma@example.com"
    assert normalize_email(None) == ""


# -----------------------------------------------------------------------------
# Entity Query Tests
# -----------------------------------------------------------------------------

def test_customer_lookup_by_id_and_email(temp_store: DataStore):
    """Customer lookup works by ID (normalized) and email (case-insensitive)."""
    # By ID with and without hyphen
    c1 = temp_store.customer("C101")
    assert c1 is not None
    assert c1["name"] == "Aarav Sharma"

    c1_hyphen = temp_store.customer("c-101")
    assert c1_hyphen == c1

    # By email (exact and uppercase with spaces)
    c1_email = temp_store.customer("aarav.sharma@example.com")
    assert c1_email == c1

    c1_email_upper = temp_store.customer("  AARAV.SHARMA@EXAMPLE.COM  ")
    assert c1_email_upper == c1

    # Customer 2 (stored with hyphen)
    c2 = temp_store.customer("C102")
    assert c2 is not None
    assert c2["customer_id"] == "C-102"

    c2_hyphen = temp_store.customer("C-102")
    assert c2_hyphen == c2


def test_customer_lookup_missing_returns_none(temp_store: DataStore):
    """Missing customer queries must return None without raising."""
    assert temp_store.customer("NONEXISTENT") is None
    assert temp_store.customer("nonexistent@example.com") is None
    assert temp_store.customer(None) is None
    assert temp_store.customer("") is None


def test_order_lookup_normalised_ids(temp_store: DataStore):
    """Order lookup matches NM1042 and NM-1042 as equal."""
    o1 = temp_store.order("NM-1042")
    assert o1 is not None
    assert o1["order_value"] == 2499.0

    o2 = temp_store.order("NM1042")
    assert o2 == o1

    o3 = temp_store.order("  nm-1042  ")
    assert o3 == o1


def test_order_lookup_missing_returns_none(temp_store: DataStore):
    """Missing order queries must return None without raising."""
    assert temp_store.order("NM-9999") is None
    assert temp_store.order(None) is None
    assert temp_store.order("") is None


def test_orders_for_customer(temp_store: DataStore):
    """Orders for customer returns list of matching orders, empty list if none."""
    orders = temp_store.orders_for_customer("C101")
    assert len(orders) == 1
    assert orders[0]["order_id"] == "NM-1042"

    # Hyphenated lookup
    orders_hyphen = temp_store.orders_for_customer("c-101")
    assert orders_hyphen == orders

    # Missing returns empty list
    assert temp_store.orders_for_customer("UNKNOWN") == []
    assert temp_store.orders_for_customer(None) == []


def test_items_for_order(temp_store: DataStore):
    """Items for order returns item list (embedded or standalone)."""
    items = temp_store.items_for_order("NM-1042")
    assert len(items) == 1
    assert items[0]["sku"] == "NM-ELEC-102"

    # Normalized lookup
    items_norm = temp_store.items_for_order("NM1042")
    assert items_norm == items

    # Missing returns empty list
    assert temp_store.items_for_order("UNKNOWN") == []
    assert temp_store.items_for_order(None) == []


def test_product_lookup(temp_store: DataStore):
    """Product lookup by SKU with normalized IDs."""
    prod = temp_store.product("NM-ELEC-101")
    assert prod is not None
    assert prod["name"] == "ANC Headphones"

    prod_norm = temp_store.product("NMELEC101")
    assert prod_norm == prod

    # Missing returns None
    assert temp_store.product("NONEXISTENT") is None
    assert temp_store.product(None) is None


def test_conversations_and_tickets(temp_store: DataStore):
    """Conversation history and tickets for customer."""
    convs = temp_store.conversations("C101")
    assert len(convs) == 1
    assert convs[0]["conversation_id"] == "CONV-1"
    assert temp_store.conversations("UNKNOWN") == []
    assert temp_store.conversations(None) == []

    tickets = temp_store.tickets_for_customer("C101")
    assert len(tickets) == 1
    assert tickets[0]["ticket_id"] == "ST-1001"
    assert temp_store.tickets_for_customer("UNKNOWN") == []
    assert temp_store.tickets_for_customer(None) == []


def test_policies(temp_store: DataStore):
    """Policies() returns all versions."""
    pols = temp_store.policies()
    assert len(pols) == 2
    versions = [p["version"] for p in pols]
    assert "v1" in versions
    assert "v2" in versions


# -----------------------------------------------------------------------------
# Runtime Write Helpers Tests (Never modify source files)
# -----------------------------------------------------------------------------

def test_runtime_write_helpers_append_and_isolate_source(temp_store: DataStore):
    """Write helpers append to data/runtime/*.json and never touch source files."""
    source_policy_file = temp_store.data_dir / "policies.json"
    source_policy_mtime_before = source_policy_file.stat().st_mtime
    source_policy_content_before = source_policy_file.read_text(encoding="utf-8")

    # 1. Add refund
    refund_rec = {"order_id": "NM-1042", "customer_id": "C101", "amount": 2499.0, "reason": "damaged"}
    temp_store.add_refund(refund_rec)

    # 2. Add return
    return_rec = {"order_id": "NM-1042", "customer_id": "C101", "reason": "size_issue"}
    temp_store.add_return(return_rec)

    # 3. Add ticket
    ticket_rec = {"ticket_id": "ST-2001", "customer_id": "C101", "summary": "Runtime ticket", "status": "open"}
    temp_store.add_ticket(ticket_rec)

    # 4. Add escalation
    escalation_rec = {"customer_id": "C101", "summary": "Escalated issue", "priority": "high"}
    temp_store.add_escalation(escalation_rec)

    # Verify source files were NOT modified
    assert source_policy_file.stat().st_mtime == source_policy_mtime_before
    assert source_policy_file.read_text(encoding="utf-8") == source_policy_content_before

    # Verify runtime files exist in data/runtime/
    runtime_dir = temp_store.runtime_dir
    assert (runtime_dir / "refunds.json").exists()
    assert (runtime_dir / "returns.json").exists()
    assert (runtime_dir / "tickets.json").exists()
    assert (runtime_dir / "escalations.json").exists()

    # Verify newly added ticket is visible in tickets_for_customer
    combined_tickets = temp_store.tickets_for_customer("C101")
    ticket_ids = [t.get("ticket_id") or t.get("id") for t in combined_tickets]
    assert "ST-1001" in ticket_ids
    assert "ST-2001" in ticket_ids

    # Append second refund and check file has both
    second_refund = {"order_id": "NM-1101", "customer_id": "C-102", "amount": 4999.0, "reason": "late"}
    temp_store.add_refund(second_refund)

    with open(runtime_dir / "refunds.json", "r", encoding="utf-8") as f:
        refunds_on_disk = json.load(f)
    assert len(refunds_on_disk) == 2


# -----------------------------------------------------------------------------
# Reload-On-Change Tests (mtime detection without restart)
# -----------------------------------------------------------------------------

def test_reload_on_change_policy_mutation(temp_store: DataStore):
    """Mutating the policy file on disk changes policies() without restarting DataStore."""
    # Initial state
    pols_initial = temp_store.policies()
    v1_initial = next(p for p in pols_initial if p["version"] == "v1")
    assert v1_initial["base_refund_window_days"] == 7

    # Mutate policies.json on disk (window 7 -> 10)
    policy_file = temp_store.data_dir / "policies.json"
    updated_policies = [
        {"version": "v1", "base_refund_window_days": 10, "approval_threshold": 5000.0},
        {"version": "v2", "base_refund_window_days": 14, "approval_threshold": 8000.0},
    ]

    time.sleep(0.05)  # Ensure filesystem timestamp tick
    with open(policy_file, "w", encoding="utf-8") as f:
        json.dump(updated_policies, f)

    # Force mtime forward if filesystem timestamp resolution is coarse
    new_mtime = time.time() + 2.0
    os.utime(policy_file, (new_mtime, new_mtime))

    # Query DataStore again WITHOUT creating a new instance or calling reload explicitly
    pols_reloaded = temp_store.policies()
    v1_reloaded = next(p for p in pols_reloaded if p["version"] == "v1")
    assert v1_reloaded["base_refund_window_days"] == 10
    v2_reloaded = next(p for p in pols_reloaded if p["version"] == "v2")
    assert v2_reloaded["base_refund_window_days"] == 14


def test_reload_on_new_file_added(temp_store: DataStore):
    """Adding a new file dynamically is picked up by DataStore automatically."""
    assert temp_store.order("NM-2000") is None

    # Dynamically create extra_orders.json
    extra_orders = [
        {
            "order_id": "NM-2000",
            "customer_id": "C101",
            "order_value": 899.0,
            "status": "delivered",
        }
    ]
    new_file = temp_store.data_dir / "extra_orders.json"
    with open(new_file, "w", encoding="utf-8") as f:
        json.dump(extra_orders, f)

    # Query without restart
    found = temp_store.order("NM-2000")
    assert found is not None
    assert found["order_value"] == 899.0


# -----------------------------------------------------------------------------
# CSV Loading Test
# -----------------------------------------------------------------------------

def test_csv_file_loading(tmp_path: Path):
    """Ensure CSV files are loaded correctly into dicts indexed by id and customer_id."""
    data_dir = tmp_path / "csv_data"
    data_dir.mkdir(parents=True)

    # Create customers.csv
    with open(data_dir / "customers.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "email", "loyalty_tier"])
        writer.writeheader()
        writer.writerow({"id": "C201", "name": "Rahul Verma", "email": "rahul@test.com", "loyalty_tier": "gold"})

    # Create orders.csv
    with open(data_dir / "orders.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "customer_id", "order_value", "status"])
        writer.writeheader()
        writer.writerow({"id": "NM-3001", "customer_id": "C201", "order_value": "1500", "status": "delivered"})

    ds = DataStore(data_dir=data_dir)

    cust = ds.customer("C201")
    assert cust is not None
    assert cust["name"] == "Rahul Verma"

    ordr = ds.order("NM3001")
    assert ordr is not None
    assert ordr["id"] == "NM-3001"

    orders = ds.orders_for_customer("C201")
    assert len(orders) == 1
