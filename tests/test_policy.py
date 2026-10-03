"""Unit tests for agent/policy_engine.py verifying version selection, return windows,
restocking fees, refund capping, and deterministic eligibility reason codes.
"""

from __future__ import annotations

import pytest

from agent.policy_engine import (
    REASON_ALREADY_REFUNDED,
    REASON_NOT_DELIVERED,
    REASON_OK,
    REASON_OTP_DISPUTE,
    REASON_PAYMENT_PENDING,
    REASON_RETURNS_NOT_ALLOWED,
    REASON_WARRANTY_EXPIRED,
    REASON_WINDOW_EXPIRED,
    effective_window,
    eligibility,
    max_refund,
    restocking_fee,
    return_deadline,
    select_policy,
)


@pytest.fixture
def sample_policies() -> list[dict]:
    return [
        {
            "version": "v1",
            "effective_date": "2026-01-01T00:00:00+05:30",
            "base_refund_window_days": 7,
            "loyalty_extensions": {
                "regular": 0,
                "silver": 3,
                "gold": 7,
                "platinum": 14,
            },
            "category_windows": {
                "electronics": 7,
                "fashion": 10,
                "personal_care": 0,
            },
            "restocking_fees": {
                "electronics": 0.15,
                "fashion": 0.05,
                "default": 0.05,
            },
            "approval_threshold": 5000.00,
            "non_returnable_categories": ["personal_care", "hygiene"],
            "disallowed_fee_reasons": ["damaged", "defective", "wrong_item"],
        },
        {
            "version": "v2",
            "effective_date": "2026-10-15T00:00:00+05:30",
            "base_refund_window_days": 10,
            "loyalty_extensions": {
                "regular": 0,
                "silver": 5,
                "gold": 10,
                "platinum": 20,
            },
            "category_windows": {
                "electronics": 10,
                "fashion": 14,
                "personal_care": 0,
            },
            "restocking_fees": {
                "electronics": 0.10,
                "default": 0.05,
            },
            "approval_threshold": 7500.00,
            "non_returnable_categories": ["personal_care", "hygiene"],
            "disallowed_fee_reasons": ["damaged", "defective", "wrong_item"],
        },
    ]


# -----------------------------------------------------------------------------
# 1 & 2: Boundary Tests - Exactly Window Days Ago & One Second After Deadline
# -----------------------------------------------------------------------------

def test_delivered_exactly_window_days_ago(sample_policies: list[dict]):
    """Delivered exactly window days ago during daytime is eligible until end of deadline day."""
    policy = sample_policies[0]  # window = 7 days
    delivered_at = "2026-09-23T10:00:00+05:30"
    # Exactly 7 days later during working hours
    now_eval = "2026-09-30T10:00:00+05:30"

    order = {
        "order_id": "NM-1042",
        "status": "delivered",
        "delivered_at": delivered_at,
        "otp_verified": True,
        "payment_status": "completed",
    }
    customer = {"loyalty_tier": "regular"}
    product = {"category": "electronics", "returnable": True}

    res = eligibility(order, customer, product, policy, reason="wrong size", now=now_eval)
    assert res["eligible"] is True
    assert res["reason_code"] == REASON_OK
    assert res["window_days"] == 7
    assert res["days_left"] == 0  # Last day of window


def test_one_second_after_deadline(sample_policies: list[dict]):
    """One second after 23:59:59 of the deadline day results in WINDOW_EXPIRED."""
    policy = sample_policies[0]  # window = 7 days
    delivered_at = "2026-09-23T10:00:00+05:30"
    # Deadline day is Sep 30 (23:59:59.999999). 1 second after is Oct 01 00:00:00
    now_eval = "2026-10-01T00:00:00+05:30"

    order = {
        "order_id": "NM-1042",
        "status": "delivered",
        "delivered_at": delivered_at,
        "otp_verified": True,
        "payment_status": "completed",
    }
    customer = {"loyalty_tier": "regular"}
    product = {"category": "electronics", "returnable": True}

    res = eligibility(order, customer, product, policy, reason="changed mind", now=now_eval)
    assert res["eligible"] is False
    assert res["reason_code"] == REASON_WINDOW_EXPIRED
    assert res["days_left"] == 0


# -----------------------------------------------------------------------------
# 3: Premium Tier Extension
# -----------------------------------------------------------------------------

def test_premium_loyalty_extension(sample_policies: list[dict]):
    """Platinum loyalty tier gets +14 days on base window, making a 12-day-old order eligible."""
    policy = sample_policies[0]
    delivered_at = "2026-09-18T10:00:00+05:30"
    now_eval = "2026-09-30T10:00:00+05:30"  # 12 days after delivery

    order = {
        "order_id": "NM-1042",
        "status": "delivered",
        "delivered_at": delivered_at,
        "otp_verified": True,
        "payment_status": "completed",
    }
    product = {"category": "electronics", "returnable": True}

    # Regular tier (7 + 0 = 7 days) -> Expired
    regular_cust = {"loyalty_tier": "regular"}
    res_reg = eligibility(order, regular_cust, product, policy, reason="return", now=now_eval)
    assert res_reg["eligible"] is False
    assert res_reg["reason_code"] == REASON_WINDOW_EXPIRED

    # Platinum tier (7 + 14 = 21 days) -> Eligible
    plat_cust = {"loyalty_tier": "platinum"}
    res_plat = eligibility(order, plat_cust, product, policy, reason="return", now=now_eval)
    assert res_plat["eligible"] is True
    assert res_plat["reason_code"] == REASON_OK
    assert res_plat["window_days"] == 21
    assert res_plat["days_left"] > 0


# -----------------------------------------------------------------------------
# 4 & 5: Restocking Fees (5% and 15%)
# -----------------------------------------------------------------------------

def test_restocking_fee_fashion_5_percent(sample_policies: list[dict]):
    """Fashion category assesses default 5% restocking fee."""
    policy = sample_policies[0]
    order_val = 1299.00
    fee = restocking_fee(policy, product_category="fashion", order_value=order_val, reason="color not liked")
    expected = round(1299.00 * 0.05, 2)
    assert fee == expected
    assert fee == 64.95


def test_restocking_fee_electronics_15_percent(sample_policies: list[dict]):
    """Electronics category assesses 15% restocking fee."""
    policy = sample_policies[0]
    order_val = 4999.00
    fee = restocking_fee(policy, product_category="electronics", order_value=order_val, reason="found cheaper")
    expected = round(4999.00 * 0.15, 2)
    assert fee == expected
    assert fee == 749.85


# -----------------------------------------------------------------------------
# 6: Damaged Item - No Restocking Fee
# -----------------------------------------------------------------------------

def test_restocking_fee_damaged_or_defective_is_zero(sample_policies: list[dict]):
    """Damaged or defective products incur zero restocking fee."""
    policy = sample_policies[0]
    order_val = 4999.00
    fee_damaged = restocking_fee(policy, "electronics", order_val, reason="package was damaged during delivery")
    assert fee_damaged == 0.0

    fee_defective = restocking_fee(policy, "electronics", order_val, reason="defective screen on arrival")
    assert fee_defective == 0.0

    fee_wrong = restocking_fee(policy, "fashion", 1299.00, reason="wrong_item received")
    assert fee_wrong == 0.0


# -----------------------------------------------------------------------------
# 7: Over-Claim Clamping (Rs. 10,000 on Rs. 2,499 order)
# -----------------------------------------------------------------------------

def test_overclaim_clamped_to_order_value_less_fee(sample_policies: list[dict]):
    """Max refund caps over-claim to (order_value - fee) and never exceeds truth."""
    policy = sample_policies[0]
    order_val = 2499.00
    fee = restocking_fee(policy, "electronics", order_val, reason="unwanted")  # 15% = 374.85
    net_order_val = 2499.00 - fee  # 2124.15

    # Customer claims Rs. 10,000
    claimed = 10000.00
    refund = max_refund(requested=claimed, order_value=order_val, fee=fee)
    assert refund == round(net_order_val, 2)
    assert refund == 2124.15

    # Customer claims within limit
    claimed_reasonable = 1500.00
    refund_reasonable = max_refund(requested=claimed_reasonable, order_value=order_val, fee=fee)
    assert refund_reasonable == 1500.00


# -----------------------------------------------------------------------------
# 8: Policy v2 Switching the Window
# -----------------------------------------------------------------------------

def test_policy_v2_switching_the_window(sample_policies: list[dict]):
    """Policy v2 changes base window from 7 to 10 days, flipping an 8-day-old order from expired to eligible."""
    pol_v1 = sample_policies[0]
    pol_v2 = sample_policies[1]

    delivered_at = "2026-09-22T10:00:00+05:30"
    now_eval = "2026-09-30T10:00:00+05:30"  # 8 days after delivery

    order = {
        "order_id": "NM-1042",
        "status": "delivered",
        "delivered_at": delivered_at,
        "otp_verified": True,
        "payment_status": "completed",
    }
    customer = {"loyalty_tier": "regular"}
    product = {"category": "electronics", "returnable": True}

    # Under v1 (7 days) -> WINDOW_EXPIRED
    res_v1 = eligibility(order, customer, product, pol_v1, reason="refund", now=now_eval)
    assert res_v1["eligible"] is False
    assert res_v1["reason_code"] == REASON_WINDOW_EXPIRED
    assert res_v1["policy_version"] == "v1"

    # Under v2 (10 days) -> OK
    res_v2 = eligibility(order, customer, product, pol_v2, reason="refund", now=now_eval)
    assert res_v2["eligible"] is True
    assert res_v2["reason_code"] == REASON_OK
    assert res_v2["policy_version"] == "v2"
    assert res_v2["window_days"] == 10


# -----------------------------------------------------------------------------
# 9: Policy Selection by Effective Date
# -----------------------------------------------------------------------------

def test_select_policy_by_effective_date(sample_policies: list[dict]):
    """select_policy picks latest active version whose effective_date <= reference time."""
    # Before Oct 15 -> v1
    pol_before = select_policy(sample_policies, now="2026-10-03T12:00:00+05:30")
    assert pol_before["version"] == "v1"

    # On or after Oct 15 -> v2
    pol_after = select_policy(sample_policies, now="2026-10-15T00:00:00+05:30")
    assert pol_after["version"] == "v2"


# -----------------------------------------------------------------------------
# 10: Not Delivered Status
# -----------------------------------------------------------------------------

def test_eligibility_not_delivered(sample_policies: list[dict]):
    """Shipped / in-transit orders cannot be returned before delivery."""
    policy = sample_policies[0]
    order = {
        "order_id": "NM-1102",
        "status": "shipped",
        "delivered_at": None,
        "otp_verified": False,
        "payment_status": "completed",
    }
    res = eligibility(order, None, None, policy, reason="where is my item")
    assert res["eligible"] is False
    assert res["reason_code"] == REASON_NOT_DELIVERED


# -----------------------------------------------------------------------------
# 11: Payment Pending
# -----------------------------------------------------------------------------

def test_eligibility_payment_pending(sample_policies: list[dict]):
    """Orders with pending payment cannot receive refunds."""
    policy = sample_policies[0]
    order = {
        "order_id": "NM-1410",
        "status": "pending_payment",
        "delivered_at": None,
        "payment_status": "pending",
    }
    res = eligibility(order, None, None, policy, reason="refund request")
    assert res["eligible"] is False
    assert res["reason_code"] == REASON_PAYMENT_PENDING


# -----------------------------------------------------------------------------
# 12: Already Refunded
# -----------------------------------------------------------------------------

def test_eligibility_already_refunded(sample_policies: list[dict]):
    """Orders already marked as refunded are rejected immediately."""
    policy = sample_policies[0]
    order = {
        "order_id": "NM-1042",
        "status": "refunded",
        "already_refunded": True,
        "delivered_at": "2026-09-28T10:00:00+05:30",
        "payment_status": "completed",
    }
    res = eligibility(order, None, None, policy, reason="refund request")
    assert res["eligible"] is False
    assert res["reason_code"] == REASON_ALREADY_REFUNDED


# -----------------------------------------------------------------------------
# 13: OTP Dispute Contradiction
# -----------------------------------------------------------------------------

def test_eligibility_otp_dispute(sample_policies: list[dict]):
    """Customer claims non-delivery on OTP-verified delivered order triggers OTP_DISPUTE."""
    policy = sample_policies[0]
    order = {
        "order_id": "NM-1042",
        "status": "delivered",
        "delivered_at": "2026-09-30T14:30:00+05:30",
        "otp_verified": True,
        "payment_status": "completed",
    }
    res = eligibility(order, None, None, policy, reason="I did not receive this order")
    assert res["eligible"] is False
    assert res["reason_code"] == REASON_OTP_DISPUTE


# -----------------------------------------------------------------------------
# 14: Non-Returnable Category (Hygiene / Personal Care)
# -----------------------------------------------------------------------------

def test_eligibility_non_returnable_category(sample_policies: list[dict]):
    """Personal care or explicit non-returnable items are rejected."""
    policy = sample_policies[0]
    order = {
        "order_id": "NM-1615",
        "status": "delivered",
        "delivered_at": "2026-10-02T10:00:00+05:30",
        "otp_verified": True,
        "payment_status": "completed",
    }
    product = {
        "sku": "NM-HYG-401",
        "category": "personal_care",
        "returnable": False,
    }
    res = eligibility(order, None, product, policy, reason="unopened toothbrush heads")
    assert res["eligible"] is False
    assert res["reason_code"] == REASON_RETURNS_NOT_ALLOWED


# -----------------------------------------------------------------------------
# 15: Warranty Expired Check
# -----------------------------------------------------------------------------

def test_eligibility_warranty_expired(sample_policies: list[dict]):
    """Expired return window with warranty inquiry on non-warranted item yields WARRANTY_EXPIRED."""
    policy = sample_policies[0]
    # Delivered 40 days ago
    delivered_at = "2026-08-15T10:00:00+05:30"
    now_eval = "2026-10-03T10:00:00+05:30"

    order = {
        "order_id": "NM-1042",
        "status": "delivered",
        "delivered_at": delivered_at,
        "otp_verified": True,
        "payment_status": "completed",
    }
    product = {
        "sku": "NM-FASH-201",
        "category": "fashion",
        "warranty_months": 0,
        "returnable": True,
    }
    res = eligibility(order, None, product, policy, reason="requesting warranty repair for torn seam", now=now_eval)
    assert res["eligible"] is False
    assert res["reason_code"] == REASON_WARRANTY_EXPIRED


# -----------------------------------------------------------------------------
# 16: Max Refund Bounds & Fallbacks
# -----------------------------------------------------------------------------

def test_max_refund_bounds_and_null():
    """max_refund handles None requested (full net value) and clamps negative numbers to 0."""
    # When requested is None -> net value
    assert max_refund(requested=None, order_value=1000.0, fee=50.0) == 950.0

    # When fee exceeds order value -> 0.0
    assert max_refund(requested=500.0, order_value=100.0, fee=150.0) == 0.0

    # When requested is negative -> 0.0
    assert max_refund(requested=-50.0, order_value=1000.0, fee=0.0) == 0.0


def test_return_deadline_edge_cases():
    """return_deadline handles None delivered_at and end-of-day accuracy."""
    assert return_deadline(None, 7) is None
    deadline = return_deadline("2026-09-30T10:00:00+05:30", 7)
    assert deadline is not None
    assert deadline.strftime("%Y-%m-%d") == "2026-10-07"
    assert deadline.hour == 23
    assert deadline.minute == 59
    assert deadline.second == 59


def test_effective_window_calculation(sample_policies: list[dict]):
    """effective_window computes base window + tier extensions, returning 0 for non-returnable categories."""
    policy = sample_policies[0]
    # Regular tier on electronics: 7 + 0 = 7
    assert effective_window(policy, loyalty_tier="regular", product_category="electronics") == 7
    # Gold tier on electronics: 7 + 7 = 14
    assert effective_window(policy, loyalty_tier="gold", product_category="electronics") == 14
    # Platinum tier on fashion: 10 + 14 = 24
    assert effective_window(policy, loyalty_tier="platinum", product_category="fashion") == 24
    # Personal care (non-returnable category with 0 base days): 0
    assert effective_window(policy, loyalty_tier="platinum", product_category="personal_care") == 0

