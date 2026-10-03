"""Mutation drill tests verifying policy and threshold behavior changes via data edits
without ANY code changes. Required for hackathon mid-event mutation evaluation.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from agent.data_store import DataStore
from agent.tools import (
    calculate_refund,
    check_refund_eligibility,
    create_refund,
    get_policy,
    set_data_store,
)


def _setup_mutation_env(tmp_path: Path) -> tuple[Path, DataStore]:
    """Copy repo data/ to an isolated temporary directory and point tools to it."""
    src_data = Path("data")
    dest_data = tmp_path / "data"
    shutil.copytree(src_data, dest_data)

    store = DataStore(data_dir=dest_data)
    set_data_store(store)
    return dest_data, store


def test_mutation_refund_window_7_to_10_days(tmp_path: Path):
    """Mutating refund window from 7 to 10 days flips an 8-day-old delivered order
    from WINDOW_EXPIRED to OK without any code modification.
    """
    dest_data, _store = _setup_mutation_env(tmp_path)
    policy_file = dest_data / "policies.json"
    orders_file = dest_data / "orders.json"

    # Set an order delivered 8 days ago
    with open(orders_file, "r", encoding="utf-8") as f:
        orders = json.load(f)
    orders[0]["delivered_at"] = "2026-09-25T10:00:00+05:30"
    with open(orders_file, "w", encoding="utf-8") as f:
        json.dump(orders, f)
    # Touch mtime
    os.utime(orders_file, None)

    # 1. Before mutation: 8-day-old order with 7-day window is expired
    res_before = check_refund_eligibility("NM-1042", "C101", reason="wrong size")
    assert res_before["ok"] is True
    assert res_before["data"]["eligible"] is False
    assert res_before["data"]["reason_code"] == "WINDOW_EXPIRED"

    # 2. Mutate policies.json: change window 7 -> 10
    with open(policy_file, "r", encoding="utf-8") as f:
        policies = json.load(f)
    policies[0]["base_refund_window_days"] = 10
    policies[0]["category_windows"]["electronics"] = 10

    time.sleep(0.05)
    with open(policy_file, "w", encoding="utf-8") as f:
        json.dump(policies, f)

    future_mtime = time.time() + 2.0
    os.utime(policy_file, (future_mtime, future_mtime))

    # 3. After mutation: without code restart, order is immediately eligible
    res_after = check_refund_eligibility("NM-1042", "C101", reason="wrong size")
    assert res_after["ok"] is True
    assert res_after["data"]["eligible"] is True
    assert res_after["data"]["reason_code"] == "OK"
    assert res_after["data"]["window_days"] == 10


def test_mutation_approval_threshold_lowered(tmp_path: Path):
    """Lowering approval threshold from 5000 to 1000 dynamically forces approval requirement."""
    dest_data, _store = _setup_mutation_env(tmp_path)
    policy_file = dest_data / "policies.json"

    # 1. Lower approval_threshold to 1000
    with open(policy_file, "r", encoding="utf-8") as f:
        policies = json.load(f)
    policies[0]["approval_threshold"] = 1000.00

    time.sleep(0.05)
    with open(policy_file, "w", encoding="utf-8") as f:
        json.dump(policies, f)

    future_mtime = time.time() + 2.0
    os.utime(policy_file, (future_mtime, future_mtime))

    # 2. Attempt refund of Rs. 1500 on NM-1042
    res = create_refund("NM-1042", "C101", amount=1500.00, reason="defective item")
    assert res["ok"] is False
    assert res["error"] == "approval_required"
    assert res["data"]["status"] == "APPROVAL_REQUIRED"
    assert res["data"]["approval_threshold"] == 1000.00


def test_mutation_new_policy_version_and_fee_update(tmp_path: Path):
    """Adding a new active policy version switches active rules and fees dynamically."""
    dest_data, _store = _setup_mutation_env(tmp_path)
    policy_file = dest_data / "policies.json"

    # Mutate policies: add active v3 policy with lower electronics fee (10%)
    with open(policy_file, "r", encoding="utf-8") as f:
        policies = json.load(f)

    v3_policy = {
        "version": "v3",
        "effective_date": "2026-09-01T00:00:00+05:30",
        "base_refund_window_days": 15,
        "restocking_fees": {
            "electronics": 0.08,
            "default": 0.03,
        },
        "approval_threshold": 8000.00,
        "category_windows": {"electronics": 15},
    }
    # Prepend or insert as latest active
    policies = [v3_policy] + policies

    time.sleep(0.05)
    with open(policy_file, "w", encoding="utf-8") as f:
        json.dump(policies, f)

    future_mtime = time.time() + 2.0
    os.utime(policy_file, (future_mtime, future_mtime))

    # Assert get_policy immediately returns v3
    pol_res = get_policy()
    assert pol_res["ok"] is True
    assert pol_res["data"]["version"] == "v3"
    assert pol_res["data"]["base_refund_window_days"] == 15

    # Assert calculate_refund immediately uses 8% fee instead of 15%
    calc_res = calculate_refund("NM-1042", "C101", requested=2000.00, reason="unwanted")
    assert calc_res["ok"] is True
    # 2499 * 0.08 = 199.92
    assert calc_res["data"]["restocking_fee"] == 199.92
