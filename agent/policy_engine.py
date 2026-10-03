"""Pure deterministic functions for policy evaluation: versions, return windows, fees, caps, and eligibility.

No policy numbers are hardcoded; all windows, fees, thresholds, and tier extensions
are derived from active policy records with clearly named fallback constants.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

# Clearly named default fallback constants (used strictly when policy data is missing)
DEFAULT_FALLBACK_BASE_WINDOW_DAYS: int = 7
DEFAULT_FALLBACK_RESTOCKING_FEE_RATE: float = 0.05
DEFAULT_FALLBACK_ELECTRONICS_FEE_RATE: float = 0.15
DEFAULT_FALLBACK_APPROVAL_THRESHOLD: float = 5000.00
DEFAULT_FALLBACK_WARRANTY_DAYS: int = 30
DEFAULT_FALLBACK_TIMEZONE: str = "Asia/Kolkata"

# Standard reason codes
REASON_OK: str = "OK"
REASON_WINDOW_EXPIRED: str = "WINDOW_EXPIRED"
REASON_NOT_DELIVERED: str = "NOT_DELIVERED"
REASON_RETURNS_NOT_ALLOWED: str = "RETURNS_NOT_ALLOWED"
REASON_WARRANTY_EXPIRED: str = "WARRANTY_EXPIRED"
REASON_PAYMENT_PENDING: str = "PAYMENT_PENDING"
REASON_ALREADY_REFUNDED: str = "ALREADY_REFUNDED"
REASON_OTP_DISPUTE: str = "OTP_DISPUTE"

NON_DELIVERY_KEYWORDS: tuple[str, ...] = (
    "not received",
    "never received",
    "did not receive",
    "didn't receive",
    "havent received",
    "haven't received",
    "not delivered",
    "missing package",
    "package missing",
    "didnt get",
)

DISALLOWED_FEE_KEYWORDS: tuple[str, ...] = (
    "damaged",
    "defective",
    "wrong_item",
    "faulty",
    "broken",
    "missing_item",
)


def _parse_datetime(
    dt_val: datetime | str | None,
    tz_str: str = DEFAULT_FALLBACK_TIMEZONE,
) -> datetime | None:
    """Parse ISO datetime string or datetime instance into a timezone-aware datetime."""
    if dt_val is None:
        return None
    tz_obj = ZoneInfo(tz_str)
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=tz_obj)
        return dt_val.astimezone(tz_obj)

    val_str = str(dt_val).strip()
    if not val_str:
        return None

    try:
        parsed = datetime.fromisoformat(val_str)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=tz_obj)
        return parsed.astimezone(tz_obj)
    except (ValueError, TypeError):
        return None


def select_policy(
    policies: list[dict[str, Any]],
    order: dict[str, Any] | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Select the active policy version from policy records.

    Assumption:
    Policies are selected by comparing their 'effective_date' with the reference time
    ('now', or the order's 'order_date' / 'delivered_at' if now is None). The latest active
    version whose effective_date <= reference time is returned. If no policy has an
    effective_date, or if multiple match, the one with the latest date or the last record
    in the list is returned. If policies is empty, an empty dictionary is returned.
    """
    if not policies:
        return {}

    ref_dt = _parse_datetime(now)
    if ref_dt is None and order:
        ref_dt = _parse_datetime(order.get("order_date") or order.get("delivered_at"))
    if ref_dt is None:
        ref_dt = datetime.now(ZoneInfo(DEFAULT_FALLBACK_TIMEZONE))

    active_candidates: list[tuple[datetime, str, dict[str, Any]]] = []
    fallback_candidates: list[dict[str, Any]] = []

    for pol in policies:
        if not isinstance(pol, dict):
            continue
        eff_str = pol.get("effective_date")
        version_str = str(pol.get("version", ""))
        eff_dt = _parse_datetime(eff_str)
        if eff_dt is not None:
            if eff_dt <= ref_dt:
                active_candidates.append((eff_dt, version_str, pol))
        else:
            fallback_candidates.append(pol)

    if active_candidates:
        # Sort by effective_date descending, then version string descending
        active_candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return active_candidates[0][2]

    if fallback_candidates:
        return fallback_candidates[-1]

    return policies[-1] if isinstance(policies[-1], dict) else {}


def return_deadline(
    delivered_at: datetime | str | None,
    window_days: int,
    tz: str = DEFAULT_FALLBACK_TIMEZONE,
) -> datetime | None:
    """Calculate the return deadline datetime at the END of the deadline day in the specified timezone.

    Returns None if delivered_at is None or invalid.
    """
    deliv_dt = _parse_datetime(delivered_at, tz_str=tz)
    if deliv_dt is None:
        return None

    tz_obj = ZoneInfo(tz)
    deliv_in_tz = deliv_dt.astimezone(tz_obj)
    deadline_date = deliv_in_tz.date() + timedelta(days=window_days)
    # The end of the deadline day is 23:59:59.999999
    return datetime.combine(deadline_date, time.max, tzinfo=tz_obj)


def effective_window(
    policy: dict[str, Any],
    loyalty_tier: str | None = None,
    product_category: str | None = None,
) -> int:
    """Calculate effective return window in days: base days + loyalty extension from policy data.

    Returns 0 if the product category is defined as non-returnable in policy category windows.
    """
    cat_windows = policy.get("category_windows", {})
    if product_category and product_category.lower() in cat_windows:
        base_days = int(cat_windows[product_category.lower()])
    else:
        base_days = int(
            policy.get("base_refund_window_days")
            or policy.get("window_days")
            or DEFAULT_FALLBACK_BASE_WINDOW_DAYS
        )

    # If base window is zero (non-returnable), loyalty does not extend returns
    if base_days == 0:
        return 0

    tier_key = str(loyalty_tier).lower() if loyalty_tier else "regular"
    loyalty_map = policy.get("loyalty_extensions", {})
    loyalty_add = int(loyalty_map.get(tier_key, 0))

    return base_days + loyalty_add


def restocking_fee(
    policy: dict[str, Any],
    product_category: str | None,
    order_value: float,
    reason: str | None = None,
) -> float:
    """Calculate restocking fee amount.

    Returns 0.0 for damaged/defective items or approved exceptions; otherwise
    calculates fee amount based on policy category or default rates.
    """
    if reason:
        reason_norm = str(reason).lower()
        disallowed = policy.get("disallowed_fee_reasons", DISALLOWED_FEE_KEYWORDS)
        if any(kw in reason_norm for kw in disallowed):
            return 0.0

    fee_map = policy.get("restocking_fees", {})
    rate: float
    if product_category and product_category.lower() in fee_map:
        rate = float(fee_map[product_category.lower()])
    elif "default" in fee_map:
        rate = float(fee_map["default"])
    else:
        rate = float(policy.get("restocking_fee_rate", DEFAULT_FALLBACK_RESTOCKING_FEE_RATE))

    # If rate is expressed as a decimal ratio (e.g. <= 1.0), multiply by order_value
    val = float(order_value)
    if rate <= 1.0:
        fee_amount = val * rate
    else:
        fee_amount = rate

    capped_fee = max(0.0, min(fee_amount, val))
    return round(capped_fee, 2)


def max_refund(
    requested: float | None,
    order_value: float,
    fee: float = 0.0,
) -> float:
    """Calculate maximum allowable refund: min(requested, order_value - fee), never below 0."""
    val = float(order_value)
    fee_val = float(fee)
    net_allowed = max(0.0, val - fee_val)

    if requested is None:
        return round(net_allowed, 2)

    req = float(requested)
    approved = min(req, net_allowed)
    return round(max(0.0, approved), 2)


def eligibility(
    order: dict[str, Any],
    customer: dict[str, Any] | None,
    product: dict[str, Any] | None,
    policy: dict[str, Any],
    reason: str | None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Deterministic eligibility evaluator for refund and return requests.

    Returns a dictionary with keys:
      eligible: bool
      reason_code: OK | WINDOW_EXPIRED | NOT_DELIVERED | RETURNS_NOT_ALLOWED |
                   WARRANTY_EXPIRED | PAYMENT_PENDING | ALREADY_REFUNDED | OTP_DISPUTE
      window_days: int
      deadline: str | None (ISO format)
      days_left: int | None
      policy_version: str
    """
    policy_version = str(policy.get("version", ""))
    reason_text = str(reason or "").strip().lower()

    # 1. ALREADY_REFUNDED
    if (
        order.get("status") == "refunded"
        or order.get("already_refunded") is True
        or bool(order.get("refund_id"))
        or bool(order.get("refunded_at"))
    ):
        return {
            "eligible": False,
            "reason_code": REASON_ALREADY_REFUNDED,
            "window_days": 0,
            "deadline": None,
            "days_left": 0,
            "policy_version": policy_version,
        }

    # 2. PAYMENT_PENDING
    payment_status = str(order.get("payment_status", "")).lower()
    order_status = str(order.get("status", "")).lower()
    if payment_status == "pending" or order_status == "pending_payment":
        return {
            "eligible": False,
            "reason_code": REASON_PAYMENT_PENDING,
            "window_days": 0,
            "deadline": None,
            "days_left": 0,
            "policy_version": policy_version,
        }

    # 3. OTP_DISPUTE: Order delivered + OTP verified, but customer claims non-delivery
    is_delivered = order_status == "delivered" and bool(order.get("delivered_at"))
    is_otp_verified = bool(order.get("otp_verified"))
    is_claiming_non_delivery = any(kw in reason_text for kw in NON_DELIVERY_KEYWORDS)

    if is_delivered and is_otp_verified and is_claiming_non_delivery:
        return {
            "eligible": False,
            "reason_code": REASON_OTP_DISPUTE,
            "window_days": 0,
            "deadline": None,
            "days_left": 0,
            "policy_version": policy_version,
        }

    # 4. NOT_DELIVERED
    if not is_delivered:
        return {
            "eligible": False,
            "reason_code": REASON_NOT_DELIVERED,
            "window_days": 0,
            "deadline": None,
            "days_left": 0,
            "policy_version": policy_version,
        }

    # 5. RETURNS_NOT_ALLOWED
    category = (
        product.get("category")
        if product
        else order.get("category")
    )
    is_returnable = (
        product.get("returnable")
        if product and "returnable" in product
        else order.get("returnable")
    )

    non_returnable_cats = [
        c.lower() for c in policy.get("non_returnable_categories", ["personal_care", "hygiene"])
    ]
    if (
        is_returnable is False
        or (category and category.lower() in non_returnable_cats)
    ):
        return {
            "eligible": False,
            "reason_code": REASON_RETURNS_NOT_ALLOWED,
            "window_days": 0,
            "deadline": None,
            "days_left": 0,
            "policy_version": policy_version,
        }

    # Calculate window and deadline
    tier = customer.get("loyalty_tier") if customer else None
    window = effective_window(policy, loyalty_tier=tier, product_category=category)
    if window == 0:
        return {
            "eligible": False,
            "reason_code": REASON_RETURNS_NOT_ALLOWED,
            "window_days": 0,
            "deadline": None,
            "days_left": 0,
            "policy_version": policy_version,
        }

    deadline_dt = return_deadline(order.get("delivered_at"), window_days=window)
    eval_dt = _parse_datetime(now) or datetime.now(ZoneInfo(DEFAULT_FALLBACK_TIMEZONE))

    # Compute days left until deadline
    days_left: int | None = None
    if deadline_dt:
        diff_sec = (deadline_dt - eval_dt).total_seconds()
        days_left = max(0, int(diff_sec // 86400)) if diff_sec > 0 else 0

    # 6. Check return window deadline
    if deadline_dt and eval_dt > deadline_dt:
        # Check if customer has an active warranty path
        is_warranty_reason = "warranty" in reason_text
        warranty_months = (
            int(product.get("warranty_months", 0))
            if product and "warranty_months" in product
            else 0
        )

        if is_warranty_reason and warranty_months <= 0:
            return {
                "eligible": False,
                "reason_code": REASON_WARRANTY_EXPIRED,
                "window_days": window,
                "deadline": deadline_dt.isoformat(),
                "days_left": 0,
                "policy_version": policy_version,
            }

        return {
            "eligible": False,
            "reason_code": REASON_WINDOW_EXPIRED,
            "window_days": window,
            "deadline": deadline_dt.isoformat(),
            "days_left": 0,
            "policy_version": policy_version,
        }

    # 7. All checks passed
    return {
        "eligible": True,
        "reason_code": REASON_OK,
        "window_days": window,
        "deadline": deadline_dt.isoformat() if deadline_dt else None,
        "days_left": days_left,
        "policy_version": policy_version,
    }
