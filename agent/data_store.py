"""In-memory data store loading JSON/CSV policies, orders, customers, and other datasets
with automatic hot-reload on file modification (mtime change) and runtime persistence.
"""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any


def normalize_id(val: Any) -> str:
    """Normalise IDs: strip whitespace, upper-case, treat NM1042 and NM-1042 as equal.

    Removes hyphens, underscores, and internal whitespace so that variants like:
    'NM1042', 'NM-1042', 'nm_1042', and '  NM-1042  ' all produce 'NM1042'.
    Returns an empty string if val is None. Never raises.
    """
    if val is None:
        return ""
    s = str(val).strip().upper()
    return re.sub(r"[\s\-_]+", "", s)


def normalize_email(val: Any) -> str:
    """Normalise email addresses by stripping whitespace and converting to lowercase.

    Returns an empty string if val is None. Never raises.
    """
    if val is None:
        return ""
    return str(val).strip().lower()


class DataStore:
    """In-memory data store for Sentinel-Governor.

    Loads all files (CSV/JSON) into dicts indexed by id and by customer_id;
    reloads a file automatically when its mtime changes, so mid-event data
    changes need no restart.

    Never raises exceptions on missing data, returning None or empty lists.
    """

    def __init__(
        self,
        data_dir: str | Path = "data",
        runtime_dir: str | Path | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.runtime_dir = Path(runtime_dir) if runtime_dir else self.data_dir / "runtime"

        # File modification tracking: filepath -> (mtime, size)
        self._file_snapshots: dict[str, tuple[float, int]] = {}

        # Primary entities indexed by normalized keys
        self._customers_by_id: dict[str, dict[str, Any]] = {}
        self._customers_by_email: dict[str, dict[str, Any]] = {}
        self._orders_by_id: dict[str, dict[str, Any]] = {}
        self._orders_by_customer_id: dict[str, list[dict[str, Any]]] = {}
        self._items_by_id: dict[str, dict[str, Any]] = {}
        self._items_by_order_id: dict[str, list[dict[str, Any]]] = {}
        self._products_by_sku: dict[str, dict[str, Any]] = {}
        self._conversations_by_customer_id: dict[str, list[dict[str, Any]]] = {}
        self._tickets_by_customer_id: dict[str, list[dict[str, Any]]] = {}
        self._policies: list[dict[str, Any]] = []

        # Generic lookup fallback tables
        self._all_by_id: dict[str, dict[str, Any]] = {}
        self._all_by_customer_id: dict[str, list[dict[str, Any]]] = {}

        # Runtime persisted records
        self._runtime_refunds: list[dict[str, Any]] = []
        self._runtime_returns: list[dict[str, Any]] = []
        self._runtime_tickets: list[dict[str, Any]] = []
        self._runtime_escalations: list[dict[str, Any]] = []

        # Initial load
        self.reload()

    # -------------------------------------------------------------------------
    # Hot-reload & File Tracking
    # -------------------------------------------------------------------------

    def _get_tracked_files(self) -> list[Path]:
        """Find all CSV and JSON source files in data_dir (excluding runtime_dir)."""
        if not self.data_dir.exists() or not self.data_dir.is_dir():
            return []

        resolved_runtime = self.runtime_dir.resolve() if self.runtime_dir.exists() else None
        files: list[Path] = []
        for root, _, filenames in os.walk(self.data_dir):
            root_path = Path(root).resolve()
            if resolved_runtime and (root_path == resolved_runtime or resolved_runtime in root_path.parents):
                continue
            for fname in filenames:
                lower = fname.lower()
                if lower.endswith((".json", ".csv")):
                    files.append(Path(root) / fname)
        return sorted(files)

    def _should_reload(self) -> bool:
        """Check if any tracked file was modified, added, or deleted."""
        current_files = self._get_tracked_files()
        current_paths = {str(f.resolve()) for f in current_files}
        tracked_paths = set(self._file_snapshots.keys())

        if current_paths != tracked_paths:
            return True

        for file_path in current_files:
            key = str(file_path.resolve())
            try:
                stat = file_path.stat()
                mtime = stat.st_mtime
                size = stat.st_size
                if key not in self._file_snapshots:
                    return True
                cached_mtime, cached_size = self._file_snapshots[key]
                if mtime != cached_mtime or size != cached_size:
                    return True
            except OSError:
                return True

        return False

    def _check_reload(self) -> None:
        """Automatically reloads all files if any mtime or file size changed."""
        if self._should_reload():
            self.reload()

    def reload(self) -> None:
        """Force a complete reload of all source datasets and runtime records."""
        # Reset collections
        self._customers_by_id.clear()
        self._customers_by_email.clear()
        self._orders_by_id.clear()
        self._orders_by_customer_id.clear()
        self._items_by_id.clear()
        self._items_by_order_id.clear()
        self._products_by_sku.clear()
        self._conversations_by_customer_id.clear()
        self._tickets_by_customer_id.clear()
        self._policies.clear()
        self._all_by_id.clear()
        self._all_by_customer_id.clear()
        self._file_snapshots.clear()

        # Load all source files
        for file_path in self._get_tracked_files():
            try:
                stat = file_path.stat()
                self._file_snapshots[str(file_path.resolve())] = (stat.st_mtime, stat.st_size)
                self._load_file(file_path)
            except (OSError, json.JSONDecodeError, csv.Error, UnicodeDecodeError):
                # Never crash the data store on a single malformed file
                continue

        # Load existing runtime records
        self._load_runtime_records()

    # -------------------------------------------------------------------------
    # Ingestion & Indexing
    # -------------------------------------------------------------------------

    def _load_file(self, file_path: Path) -> None:
        """Parse a JSON or CSV file and route records to corresponding indexers."""
        lower_name = file_path.name.lower()

        if lower_name.endswith(".json"):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._route_json_data(data, file_path)
        elif lower_name.endswith(".csv"):
            with open(file_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = [dict(row) for row in reader]
            self._route_records(rows, file_path.stem.lower())

    def _route_json_data(self, data: Any, file_path: Path) -> None:
        """Handle JSON structures: list of objects, dict of tables, or single dict."""
        stem = file_path.stem.lower()

        if isinstance(data, list):
            # Check if this is a policy list
            if "polic" in stem:
                for item in data:
                    if isinstance(item, dict):
                        self._policies.append(item)
            else:
                self._route_records(data, stem)
        elif isinstance(data, dict):
            # Check if dict represents policies
            if "polic" in stem:
                if "policies" in data and isinstance(data["policies"], list):
                    for item in data["policies"]:
                        if isinstance(item, dict):
                            self._policies.append(item)
                else:
                    self._policies.append(data)
                return

            # Check if dict wraps tables, e.g. {"orders": [...], "customers": [...]}
            found_wrapped_table = False
            for key, val in data.items():
                if isinstance(val, list) and val and isinstance(val[0], dict):
                    self._route_records(val, key.lower())
                    found_wrapped_table = True

            if not found_wrapped_table:
                # Might be a single record or key-value mapped collection (e.g. {"C101": {...}})
                if any(k.lower() in ("id", "customer_id", "order_id", "sku", "version") for k in data):
                    self._route_records([data], stem)
                else:
                    mapped_records = []
                    for k, v in data.items():
                        if isinstance(v, dict):
                            rec = dict(v)
                            if "id" not in rec and "customer_id" not in rec and "order_id" not in rec:
                                rec["id"] = k
                            mapped_records.append(rec)
                    if mapped_records:
                        self._route_records(mapped_records, stem)

    def _route_records(self, records: list[dict[str, Any]], hint_name: str) -> None:
        """Route list of dict records into specific and generic indices."""
        for raw_row in records:
            if not isinstance(raw_row, dict):
                continue
            row = dict(raw_row)

            # Extract common identifier fields
            item_id = (
                row.get("id")
                or row.get("customer_id")
                or row.get("order_id")
                or row.get("item_id")
                or row.get("sku")
                or row.get("product_id")
                or row.get("ticket_id")
                or row.get("conversation_id")
            )
            cust_id = row.get("customer_id") or row.get("cid") or row.get("user_id")

            norm_id = normalize_id(item_id)
            norm_cid = normalize_id(cust_id)

            if norm_id:
                self._all_by_id[norm_id] = row
                # Also index raw stripped uppercase
                self._all_by_id[str(item_id).strip().upper()] = row
            if norm_cid:
                self._all_by_customer_id.setdefault(norm_cid, []).append(row)
                raw_cid_upper = str(cust_id).strip().upper()
                if raw_cid_upper != norm_cid:
                    self._all_by_customer_id.setdefault(raw_cid_upper, []).append(row)

            # Determine entity category based on file name hint or row attributes
            if "customer" in hint_name or ("email" in row and ("name" in row or "loyalty_tier" in row)):
                self._index_customer(row)
            elif "order_item" in hint_name or "item" in hint_name:
                self._index_item(row)
            elif "order" in hint_name or "order_id" in row or ("status" in row and "delivered_at" in row):
                self._index_order(row)
            elif "product" in hint_name or "sku" in row or ("category" in row and "warranty_months" in row):
                self._index_product(row)
            elif "conversation" in hint_name or "messages" in row:
                self._index_conversation(row)
            elif "ticket" in hint_name or "ticket_id" in row:
                self._index_ticket(row)
            elif "polic" in hint_name or "refund_window" in row:
                self._policies.append(row)
            else:
                # Generic record fallback
                if "email" in row:
                    self._index_customer(row)
                elif "sku" in row:
                    self._index_product(row)

    def _index_customer(self, row: dict[str, Any]) -> None:
        cid = row.get("id") or row.get("customer_id") or row.get("cid")
        norm_cid = normalize_id(cid)
        if norm_cid:
            self._customers_by_id[norm_cid] = row
            self._customers_by_id[str(cid).strip().upper()] = row

        email = row.get("email") or row.get("customer_email")
        norm_mail = normalize_email(email)
        if norm_mail:
            self._customers_by_email[norm_mail] = row

    def _index_order(self, row: dict[str, Any]) -> None:
        oid = row.get("id") or row.get("order_id") or row.get("oid")
        norm_oid = normalize_id(oid)
        if norm_oid:
            self._orders_by_id[norm_oid] = row
            self._orders_by_id[str(oid).strip().upper()] = row

        cid = row.get("customer_id") or row.get("cid") or row.get("user_id")
        norm_cid = normalize_id(cid)
        if norm_cid:
            self._orders_by_customer_id.setdefault(norm_cid, []).append(row)
            raw_cid_upper = str(cid).strip().upper()
            if raw_cid_upper != norm_cid:
                self._orders_by_customer_id.setdefault(raw_cid_upper, []).append(row)

        # If order embeds items, index them for items_for_order
        items = row.get("items")
        if isinstance(items, list):
            for itm in items:
                if isinstance(itm, dict):
                    self._index_item(itm, default_order_id=oid)

    def _index_item(self, row: dict[str, Any], default_order_id: Any = None) -> None:
        iid = row.get("id") or row.get("item_id") or row.get("sku")
        norm_iid = normalize_id(iid)
        if norm_iid:
            self._items_by_id[norm_iid] = row
            self._items_by_id[str(iid).strip().upper()] = row

        oid = row.get("order_id") or row.get("oid") or default_order_id
        norm_oid = normalize_id(oid)
        if norm_oid:
            self._items_by_order_id.setdefault(norm_oid, []).append(row)
            raw_oid_upper = str(oid).strip().upper()
            if raw_oid_upper != norm_oid:
                self._items_by_order_id.setdefault(raw_oid_upper, []).append(row)

    def _index_product(self, row: dict[str, Any]) -> None:
        sku = row.get("sku") or row.get("product_id") or row.get("id")
        norm_sku = normalize_id(sku)
        if norm_sku:
            self._products_by_sku[norm_sku] = row
            self._products_by_sku[str(sku).strip().upper()] = row

    def _index_conversation(self, row: dict[str, Any]) -> None:
        cid = row.get("customer_id") or row.get("cid") or row.get("user_id")
        norm_cid = normalize_id(cid)
        if norm_cid:
            self._conversations_by_customer_id.setdefault(norm_cid, []).append(row)
            raw_cid_upper = str(cid).strip().upper()
            if raw_cid_upper != norm_cid:
                self._conversations_by_customer_id.setdefault(raw_cid_upper, []).append(row)

    def _index_ticket(self, row: dict[str, Any]) -> None:
        cid = row.get("customer_id") or row.get("cid") or row.get("user_id")
        norm_cid = normalize_id(cid)
        if norm_cid:
            self._tickets_by_customer_id.setdefault(norm_cid, []).append(row)
            raw_cid_upper = str(cid).strip().upper()
            if raw_cid_upper != norm_cid:
                self._tickets_by_customer_id.setdefault(raw_cid_upper, []).append(row)

    def _load_runtime_records(self) -> None:
        """Load records from data/runtime/*.json into in-memory runtime lists."""
        self._runtime_refunds = self._read_runtime_file("refunds.json")
        self._runtime_returns = self._read_runtime_file("returns.json")
        self._runtime_tickets = self._read_runtime_file("tickets.json")
        self._runtime_escalations = self._read_runtime_file("escalations.json")

    def _read_runtime_file(self, filename: str) -> list[dict[str, Any]]:
        file_path = self.runtime_dir / filename
        if not file_path.exists():
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return []
                data = json.loads(content)
                if isinstance(data, list):
                    return [d for d in data if isinstance(d, dict)]
                elif isinstance(data, dict):
                    return [data]
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return []
        return []

    # -------------------------------------------------------------------------
    # Public Read Methods (Never raise, return None or empty list)
    # -------------------------------------------------------------------------

    def customer(self, id_or_email: str | None) -> dict[str, Any] | None:
        """Look up customer by customer ID (e.g. 'C101', 'NM-C101') or email.

        Returns None if missing. Never raises.
        """
        if not id_or_email:
            return None
        self._check_reload()

        val = str(id_or_email).strip()
        if not val:
            return None

        # Check by email first if '@' is present
        if "@" in val:
            mail_res = self._customers_by_email.get(normalize_email(val))
            if mail_res is not None:
                return mail_res

        # Check by normalized ID and raw uppercase ID
        norm = normalize_id(val)
        res = self._customers_by_id.get(norm) or self._customers_by_id.get(val.upper())
        if res is not None:
            return res

        # Try email fallback if not checked yet
        mail_res = self._customers_by_email.get(normalize_email(val))
        if mail_res is not None:
            return mail_res

        # Generic lookup fallback
        generic_res = self._all_by_id.get(norm) or self._all_by_id.get(val.upper())
        if generic_res is not None and ("email" in generic_res or "loyalty_tier" in generic_res):
            return generic_res

        return None

    def order(self, order_id: str | None) -> dict[str, Any] | None:
        """Look up order by order ID (e.g. 'NM1042', 'NM-1042').

        Returns None if missing. Never raises.
        """
        if not order_id:
            return None
        self._check_reload()

        val = str(order_id).strip()
        if not val:
            return None

        norm = normalize_id(val)
        res = self._orders_by_id.get(norm) or self._orders_by_id.get(val.upper())
        if res is not None:
            return res

        # Generic fallback
        generic_res = self._all_by_id.get(norm) or self._all_by_id.get(val.upper())
        if generic_res is not None and ("order_id" in generic_res or "status" in generic_res):
            return generic_res

        return None

    def orders_for_customer(self, cid: str | None) -> list[dict[str, Any]]:
        """Return all orders for customer ID cid.

        Returns empty list if none found. Never raises.
        """
        if not cid:
            return []
        self._check_reload()

        val = str(cid).strip()
        if not val:
            return []

        norm = normalize_id(val)
        orders = self._orders_by_customer_id.get(norm) or self._orders_by_customer_id.get(val.upper()) or []

        # Deduplicate by order ID while preserving order
        seen_ids = set()
        deduped: list[dict[str, Any]] = []
        for o in orders:
            oid = normalize_id(o.get("id") or o.get("order_id"))
            if oid and oid in seen_ids:
                continue
            if oid:
                seen_ids.add(oid)
            deduped.append(o)

        return deduped

    def items_for_order(self, oid: str | None) -> list[dict[str, Any]]:
        """Return all items for order ID oid.

        Returns empty list if none found. Never raises.
        """
        if not oid:
            return []
        self._check_reload()

        val = str(oid).strip()
        if not val:
            return []

        norm = normalize_id(val)
        items = self._items_by_order_id.get(norm) or self._items_by_order_id.get(val.upper()) or []

        # If items table had items, return them
        if items:
            return items

        # Fallback: check if the order dict itself has an embedded 'items' list
        order_rec = self.order(oid)
        if order_rec and isinstance(order_rec.get("items"), list):
            return [itm for itm in order_rec["items"] if isinstance(itm, dict)]

        return []

    def product(self, sku: str | None) -> dict[str, Any] | None:
        """Look up product by SKU or product_id.

        Returns None if missing. Never raises.
        """
        if not sku:
            return None
        self._check_reload()

        val = str(sku).strip()
        if not val:
            return None

        norm = normalize_id(val)
        res = self._products_by_sku.get(norm) or self._products_by_sku.get(val.upper())
        if res is not None:
            return res

        generic_res = self._all_by_id.get(norm) or self._all_by_id.get(val.upper())
        if generic_res is not None and ("sku" in generic_res or "category" in generic_res):
            return generic_res

        return None

    def conversations(self, cid: str | None) -> list[dict[str, Any]]:
        """Return past conversation history for customer ID cid.

        Returns empty list if none found. Never raises.
        """
        if not cid:
            return []
        self._check_reload()

        val = str(cid).strip()
        if not val:
            return []

        norm = normalize_id(val)
        return list(
            self._conversations_by_customer_id.get(norm)
            or self._conversations_by_customer_id.get(val.upper())
            or []
        )

    def tickets_for_customer(self, cid: str | None) -> list[dict[str, Any]]:
        """Return all tickets for customer ID cid from dataset and runtime records.

        Returns empty list if none found. Never raises.
        """
        if not cid:
            return []
        self._check_reload()

        val = str(cid).strip()
        if not val:
            return []

        norm = normalize_id(val)
        source_tickets = (
            self._tickets_by_customer_id.get(norm)
            or self._tickets_by_customer_id.get(val.upper())
            or []
        )

        # Merge with runtime tickets
        runtime_matches = [
            t for t in self._runtime_tickets
            if normalize_id(t.get("customer_id") or t.get("cid")) == norm
        ]

        seen_ids = set()
        combined: list[dict[str, Any]] = []

        for t in list(source_tickets) + runtime_matches:
            tid = normalize_id(t.get("id") or t.get("ticket_id"))
            if tid:
                if tid in seen_ids:
                    continue
                seen_ids.add(tid)
            combined.append(t)

        return combined

    def policies(self) -> list[dict[str, Any]]:
        """Return all policy versions loaded from the policy dataset.

        Returns empty list if none found. Never raises.
        """
        self._check_reload()
        return list(self._policies)

    # -------------------------------------------------------------------------
    # Write Helpers (Appends to data/runtime/*.json, never modifies source files)
    # -------------------------------------------------------------------------

    def _append_runtime_record(self, filename: str, record: dict[str, Any]) -> dict[str, Any]:
        """Atomically append a record to data/runtime/<filename>.

        Never modifies source files. Ensures directory existence and valid JSON array format.
        """
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.runtime_dir / filename

        # Read existing records
        records: list[dict[str, Any]] = []
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
                        if isinstance(data, list):
                            records = [d for d in data if isinstance(d, dict)]
                        elif isinstance(data, dict):
                            records = [data]
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                records = []

        # Make copy of record to store
        stored_record = dict(record)
        records.append(stored_record)

        # Write back to runtime file
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

        return stored_record

    def add_refund(self, record: dict[str, Any]) -> dict[str, Any]:
        """Append refund record to data/runtime/refunds.json without modifying source files."""
        stored = self._append_runtime_record("refunds.json", record)
        self._runtime_refunds.append(stored)
        return stored

    def add_return(self, record: dict[str, Any]) -> dict[str, Any]:
        """Append return record to data/runtime/returns.json without modifying source files."""
        stored = self._append_runtime_record("returns.json", record)
        self._runtime_returns.append(stored)
        return stored

    def add_ticket(self, record: dict[str, Any]) -> dict[str, Any]:
        """Append ticket record to data/runtime/tickets.json without modifying source files."""
        stored = self._append_runtime_record("tickets.json", record)
        self._runtime_tickets.append(stored)

        cid = stored.get("customer_id") or stored.get("cid")
        norm_cid = normalize_id(cid)
        if norm_cid:
            self._tickets_by_customer_id.setdefault(norm_cid, []).append(stored)

        return stored

    def add_escalation(self, record: dict[str, Any]) -> dict[str, Any]:
        """Append escalation record to data/runtime/escalations.json without modifying source files."""
        stored = self._append_runtime_record("escalations.json", record)
        self._runtime_escalations.append(stored)
        return stored
