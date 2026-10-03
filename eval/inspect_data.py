import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
"""
eval/inspect_data.py
--------------------
Dataset inspection script for NovaMart M3 (prompts/safety/eval).
Steps 2-7 of the dataset setup task.
Run from repo root:  python eval/inspect_data.py
"""

import json
import csv
import io
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def read_csv(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return None, None
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        cols = reader.fieldnames or []
    return rows, cols

def read_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def col_info(rows, cols):
    """Returns dict: col -> {type, nulls, sample}"""
    info = {}
    for c in cols:
        vals = [r.get(c, "") for r in rows]
        nulls = sum(1 for v in vals if v is None or str(v).strip() == "")
        # Infer type
        non_null = [v for v in vals if v is not None and str(v).strip() != ""]
        typ = "str"
        if non_null:
            try:
                [float(v) for v in non_null[:50]]
                if all("." not in str(v) for v in non_null[:50]):
                    typ = "int"
                else:
                    typ = "float"
            except (ValueError, TypeError):
                typ = "str"
        info[c] = {"type": typ, "nulls": nulls, "samples": [str(v) for v in vals[:3]]}
    return info

def distinct_counts(rows, col):
    c = Counter(str(r.get(col, "")).strip() for r in rows)
    return sorted(c.items(), key=lambda x: -x[1])

def sep():
    print("\n" + "=" * 90)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 summary
# ─────────────────────────────────────────────────────────────────────────────
sep()
print("STEP 1 – FILES FOUND IN ./data/")
for fn in ["conversations.json", "customers.csv", "order_items.csv",
           "orders.csv", "products.csv", "reviews.csv", "support_tickets.csv"]:
    path = os.path.join(DATA_DIR, fn)
    if os.path.exists(path):
        size = os.path.getsize(path)
        print(f"  PRESENT  {fn}  ({size:,} bytes)")
    else:
        print(f"  MISSING  {fn}")

# Policy search
print("\nPolicy-related files in ./data/:")
for fn in os.listdir(DATA_DIR):
    if "polic" in fn.lower():
        print(f"  {fn}")
else:
    print("  (none found)")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 – Per-file stats
# ─────────────────────────────────────────────────────────────────────────────

FILES = ["customers.csv", "orders.csv", "order_items.csv", "products.csv", "reviews.csv"]

all_data = {}
for fn in FILES:
    rows, cols = read_csv(fn)
    if rows is None:
        print(f"\n[MISSING] {fn}")
        continue
    all_data[fn] = rows
    info = col_info(rows, cols)
    sep()
    print(f"STEP 2 – {fn.upper()}")
    print(f"  Rows: {len(rows):,}   Cols: {len(cols)}")
    print(f"  Columns & types:")
    for c in cols:
        ci = info[c]
        print(f"    {c:<35} type={ci['type']:<6}  nulls={ci['nulls']}")
    print(f"  First 3 rows:")
    for row in rows[:3]:
        print(f"    {dict(row)}")

# JSON conversations
convs = read_json("conversations.json")
sep()
print("STEP 2 – CONVERSATIONS.JSON")
if convs is None:
    print("  MISSING")
else:
    if isinstance(convs, list):
        print(f"  Records: {len(convs):,}")
        if convs:
            print(f"  Top-level keys in first record: {list(convs[0].keys())}")
            for r in convs[:2]:
                print(f"  {repr(r)[:300]}")
    elif isinstance(convs, dict):
        print(f"  Top-level keys: {list(convs.keys())}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 – Distinct values for categorical columns
# ─────────────────────────────────────────────────────────────────────────────

CATS = {
    "orders.csv": ["status", "payment_status", "delivery_status",
                   "otp_verified", "return_requested", "refund_status",
                   "payment_method"],
    "customers.csv": ["loyalty_tier", "account_status"],
    "order_items.csv": ["status"],
    "reviews.csv": [],
}

sep()
print("STEP 3 – DISTINCT VALUES FOR CATEGORICAL COLUMNS")
for fn, cat_cols in CATS.items():
    rows = all_data.get(fn)
    if not rows:
        print(f"\n  {fn}: data missing, skipping")
        continue
    available_cols = list(rows[0].keys()) if rows else []
    target_cols = cat_cols or []
    # Auto-detect additional possible categoricals
    extra = [c for c in available_cols
             if any(kw in c.lower() for kw in
                    ["status","tier","otp","verified","payment","state",
                     "delivery","refund","return","method"])
             and c not in target_cols]
    for c in target_cols + extra:
        if c in available_cols:
            counts = distinct_counts(rows, c)
            print(f"\n  {fn} → {c}:")
            for val, cnt in counts[:20]:
                print(f"    {val!r:30} : {cnt}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 – Format inspection
# ─────────────────────────────────────────────────────────────────────────────
sep()
print("STEP 4 – FORMAT INSPECTION")

rows_c = all_data.get("customers.csv", [])
rows_o = all_data.get("orders.csv", [])
rows_oi = all_data.get("order_items.csv", [])

if rows_c:
    ids = [r.get("customer_id","") for r in rows_c[:10]]
    print(f"\n  customer_id samples: {ids}")

if rows_o:
    oids = [r.get("order_id","") for r in rows_o[:10]]
    print(f"  order_id samples   : {oids}")
    # OTP format
    otp_col = next((c for c in rows_o[0] if "otp" in c.lower()), None)
    if otp_col:
        otp_vals = [r.get(otp_col,"") for r in rows_o[:15]]
        print(f"  {otp_col} samples      : {otp_vals}")
    # Payment status
    ps_col = next((c for c in rows_o[0] if "payment" in c.lower() and "status" in c.lower()), None)
    if ps_col:
        print(f"  {ps_col} distinct: {dict(Counter(r.get(ps_col,'') for r in rows_o))}")
    # delivered_at format
    da_col = next((c for c in rows_o[0] if "deliver" in c.lower()), None)
    if da_col:
        samples = [r.get(da_col,"") for r in rows_o if r.get(da_col,"").strip()][:5]
        print(f"  {da_col} samples: {samples}")

if rows_c:
    tier_col = next((c for c in rows_c[0] if "tier" in c.lower()), None)
    if tier_col:
        print(f"  loyalty_tier distinct: {dict(Counter(r.get(tier_col,'') for r in rows_c))}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 – Data-quality issues
# ─────────────────────────────────────────────────────────────────────────────
sep()
print("STEP 5 – DATA-QUALITY FLAGS")

if rows_o:
    # Find delivered_at column
    da_col = next((c for c in rows_o[0] if "deliver" in c.lower()), None)
    # Null delivered_at on delivered orders
    status_col = next((c for c in rows_o[0] if c.lower() == "status"), None)
    if da_col and status_col:
        null_da_delivered = [r for r in rows_o
                             if "delivered" in str(r.get(status_col,"")).lower()
                             and not r.get(da_col,"").strip()]
        print(f"\n  NULL delivered_at on 'Delivered' orders: {len(null_da_delivered)}")
        for r in null_da_delivered[:3]:
            print(f"    order_id={r.get('order_id')}, status={r.get(status_col)}, delivered_at={r.get(da_col)!r}")

    # Duplicate order IDs
    oid_col = "order_id"
    oid_counts = Counter(r.get(oid_col,"") for r in rows_o)
    dups = {k: v for k, v in oid_counts.items() if v > 1}
    print(f"\n  Duplicate order_ids: {len(dups)}  (showing up to 5)")
    for k, v in list(dups.items())[:5]:
        print(f"    {k}: {v} occurrences")

    # Pending payment orders
    ps_col = next((c for c in rows_o[0] if "payment" in c.lower() and "status" in c.lower()), None)
    if ps_col:
        pending = [r for r in rows_o if "pending" in str(r.get(ps_col,"")).lower()]
        print(f"\n  Pending-payment orders: {len(pending)}")
        for r in pending[:3]:
            print(f"    {r.get('order_id')}, payment={r.get(ps_col)}, status={r.get(status_col)}")

    # Already-refunded
    rf_col = next((c for c in rows_o[0] if "refund" in c.lower()), None)
    if rf_col:
        refunded = [r for r in rows_o
                    if str(r.get(rf_col,"")).strip().lower() in ("true","yes","1","refunded","completed")]
        print(f"\n  Already-refunded orders: {len(refunded)}")
        for r in refunded[:3]:
            print(f"    {r.get('order_id')}, refund={r.get(rf_col)}, status={r.get(status_col,'')}")

    # Near return deadline (assume 7-day window as conservative default; note: policy file not found)
    if da_col:
        now = datetime(2026, 10, 3, 15, 0, 0, tzinfo=timezone.utc)
        deadline_window = 2  # days left
        near_deadline = []
        for r in rows_o:
            da = str(r.get(da_col,"")).strip()
            if not da:
                continue
            try:
                # Try ISO format
                dt = datetime.fromisoformat(da.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_days = (now - dt).days
                # 7-day assumed window
                if 5 <= age_days <= 7:
                    near_deadline.append((r.get("order_id"), da, age_days))
            except Exception:
                pass
        print(f"\n  Orders near return deadline (5-7 days since delivery, 7-day assumed window): {len(near_deadline)}")
        for oid, da, age in near_deadline[:5]:
            print(f"    order_id={oid}, delivered={da}, days_since={age}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 – Eval case selection
# ─────────────────────────────────────────────────────────────────────────────
sep()
print("STEP 6 – EVAL CASE CANDIDATES")
print("(Reading to build selection table — see markdown output at end)")

# We collect raw data for the markdown table; selection logic below
ORDER_ROWS = rows_o or []
CUST_ROWS = rows_c or []

def find_col(row, *keywords):
    for k in keywords:
        for c in row:
            if k.lower() in c.lower():
                return c
    return None

if ORDER_ROWS and CUST_ROWS:
    oid_col = find_col(ORDER_ROWS[0], "order_id") or "order_id"
    cid_col = find_col(ORDER_ROWS[0], "customer_id") or "customer_id"
    status_col = find_col(ORDER_ROWS[0], "status") or "status"
    da_col = find_col(ORDER_ROWS[0], "delivered_at", "deliver") or "delivered_at"
    otp_col = find_col(ORDER_ROWS[0], "otp") or None
    ps_col = find_col(ORDER_ROWS[0], "payment_status", "payment") or "payment_status"
    rf_col = find_col(ORDER_ROWS[0], "refund") or None
    prod_col = find_col(ORDER_ROWS[0], "product", "item_name") or "product_name"

    cust_idx = {r.get("customer_id", r.get(find_col(r, "customer_id") or "", "")): r for r in CUST_ROWS}
    tier_col = find_col(CUST_ROWS[0], "tier") if CUST_ROWS else None
    cname_col = find_col(CUST_ROWS[0], "name") if CUST_ROWS else None

    # Build order index by customer
    orders_by_cust = defaultdict(list)
    for r in ORDER_ROWS:
        orders_by_cust[r.get(cid_col, "")].append(r)

    # Category index using order_items
    rows_oi = all_data.get("order_items.csv", [])
    # Support tickets
    tickets_rows, _ = read_csv("support_tickets.csv")
    tickets_by_cust = defaultdict(list)
    if tickets_rows:
        tk_cid_col = find_col(tickets_rows[0], "customer_id") or "customer_id"
        for r in tickets_rows:
            tickets_by_cust[r.get(tk_cid_col, "")].append(r)

    candidates = []

    # 1. OTP-verified delivered order
    for r in ORDER_ROWS:
        if otp_col and str(r.get(otp_col,"")).strip().lower() in ("true","yes","1") \
                and "delivered" in str(r.get(status_col,"")).lower():
            candidates.append({"order": r, "why": "OTP-verified delivered order"})
            break

    # 2. Pending payment
    for r in ORDER_ROWS:
        if "pending" in str(r.get(ps_col,"")).lower():
            candidates.append({"order": r, "why": "Pending payment order"})
            break

    # 3. Near return deadline (5-7 days since delivery)
    now = datetime(2026, 10, 3, 15, 0, 0, tzinfo=timezone.utc)
    for r in ORDER_ROWS:
        da = str(r.get(da_col,"")).strip()
        if not da:
            continue
        try:
            dt = datetime.fromisoformat(da.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age = (now - dt).days
            if 5 <= age <= 7:
                candidates.append({"order": r, "why": f"Near return deadline ({age} days since delivery, 7d assumed)"})
                break
        except Exception:
            pass

    # 4. Premium / loyalty customer
    if tier_col:
        premium_custs = {r.get("customer_id","") for r in CUST_ROWS
                         if str(r.get(tier_col,"")).strip().lower() in ("gold","platinum","premium","vip")}
        for r in ORDER_ROWS:
            if r.get(cid_col,"") in premium_custs:
                candidates.append({"order": r, "why": f"Premium/loyalty customer"})
                break

    # 5. Customer with several orders in same product category (ambiguity)
    if rows_oi:
        cat_col = find_col(rows_oi[0], "category") or None
        item_oid = find_col(rows_oi[0], "order_id") or "order_id"
        item_cid = find_col(rows_oi[0], "customer_id") or None
        if cat_col and item_cid:
            cust_cat = defaultdict(list)
            for r in rows_oi:
                cust_cat[(r.get(item_cid,""), r.get(cat_col,""))].append(r.get(item_oid,""))
            ambiguous = [(k, v) for k, v in cust_cat.items() if len(v) >= 3]
            if ambiguous:
                (amb_cid, amb_cat), amb_oids = ambiguous[0]
                for r in ORDER_ROWS:
                    if r.get(cid_col,"") == amb_cid and r.get(oid_col,"") in amb_oids:
                        candidates.append({"order": r, "why": f"Multi-order same category ({amb_cat}), ambiguity"})
                        break

    # 6. Already refunded order
    if rf_col:
        for r in ORDER_ROWS:
            if str(r.get(rf_col,"")).strip().lower() in ("true","yes","1","refunded","completed"):
                candidates.append({"order": r, "why": "Already-refunded order"})
                break

    # 7. Customer with open support tickets
    if tickets_rows:
        for r in ORDER_ROWS:
            if tickets_by_cust.get(r.get(cid_col,"")):
                candidates.append({"order": r, "why": "Customer has open support tickets"})
                break

    # 8. Fill remaining unique candidates to get to 15
    seen_oids = {c["order"].get(oid_col,"") for c in candidates}
    for r in ORDER_ROWS:
        if len(candidates) >= 15:
            break
        if r.get(oid_col,"") not in seen_oids:
            candidates.append({"order": r, "why": "Filler – distinct order"})
            seen_oids.add(r.get(oid_col,""))

    candidates = candidates[:15]

    # Print table
    print("\n  order_id | customer_id | name | tier | product | status | delivered_at | otp_verified | payment_status | why")
    print("  " + "-"*160)
    for c in candidates:
        r = c["order"]
        cid = r.get(cid_col,"")
        cust = cust_idx.get(cid, {})
        print(f"  {r.get(oid_col,''):12} | {cid:12} | {str(cust.get(cname_col,'') if cname_col else ''):20} | "
              f"{str(cust.get(tier_col,'') if tier_col else ''):10} | "
              f"{str(r.get(prod_col,'')):25} | {str(r.get(status_col,'')):15} | "
              f"{str(r.get(da_col,'')):25} | {str(r.get(otp_col,'') if otp_col else ''):5} | "
              f"{str(r.get(ps_col,'')):15} | {c['why']}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 – Real phrasings from conversations.json and support_tickets.csv
# ─────────────────────────────────────────────────────────────────────────────
sep()
print("STEP 7 – REAL CUSTOMER PHRASINGS")

convs = read_json("conversations.json")
ticket_rows, _ = read_csv("support_tickets.csv")

phrasings = []

if convs:
    # convs may be list of conversations, each with messages
    try:
        for conv in (convs if isinstance(convs, list) else [convs]):
            msgs = conv.get("messages", conv.get("turns", []))
            for m in msgs:
                role = str(m.get("role","")).lower()
                txt = m.get("text", m.get("content", m.get("message", "")))
                if role in ("user","customer") and txt and len(txt.strip()) > 10:
                    phrasings.append(("conversations.json", txt.strip()))
                if len(phrasings) >= 20:
                    break
            if len(phrasings) >= 20:
                break
    except Exception as e:
        print(f"  Error parsing conversations.json: {e}")

if ticket_rows:
    desc_col = find_col(ticket_rows[0], "description", "message", "text", "body", "issue") or None
    if desc_col:
        for r in ticket_rows[:20]:
            txt = r.get(desc_col,"").strip()
            if txt:
                phrasings.append(("support_tickets.csv", txt))

# Print 10 sample phrasings
print("\n  # | Source | Phrasing")
for i, (src, txt) in enumerate(phrasings[:10], 1):
    display = txt[:120].replace("\n", " ")
    print(f"  {i:2}. [{src}] {display}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 90)
print("DONE. See below for markdown schema cheat-sheet.")
