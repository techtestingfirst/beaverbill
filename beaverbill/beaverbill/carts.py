"""Abandoned-cart recovery: 1h / 1d / 7d reminders then expire.

Cart cache stays the runtime truth; this DocType is the durable
trail for reminders. All sends go through notifications.notify
(best effort, never raises). Idempotent per stage.
"""

import json

import frappe
from frappe.utils import add_to_date, now_datetime

from beaverbill.beaverbill import settings as bb_settings
from beaverbill.beaverbill.notifications import notify

STAGES_HOURS = (1, 24, 168)


def _stages() -> tuple:
    try:
        raw = bb_settings.get_str("abandoned_cart_stages_hours", "")
        if raw:
            return tuple(int(h) for h in raw.split(",") if h.strip())
    except Exception:
        pass
    return STAGES_HOURS


def track_activity(user: str | None = None, cart: dict | None = None) -> None:
    """Refresh the caller's Active trail row. Never breaks the cart flow."""
    try:
        user = user or frappe.session.user
        if not user or user == "Guest":
            return
        if not cart or not cart.get("items"):
            return
        customer = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
        name = frappe.db.get_value("Hosting Abandoned Cart", {"user": user, "status": "Active"}, "name")
        snapshot = json.dumps(cart, default=str)[:8000]
        if name:
            frappe.db.set_value(
                "Hosting Abandoned Cart",
                name,
                {"last_activity_at": now_datetime(), "cart_snapshot": snapshot,
                 "customer": customer},
            )
        else:
            frappe.get_doc(
                {
                    "doctype": "Hosting Abandoned Cart",
                    "user": user,
                    "customer": customer,
                    "status": "Active",
                    "last_activity_at": now_datetime(),
                    "cart_snapshot": snapshot,
                    "reminders_sent": 0,
                }
            ).insert(ignore_permissions=True)
    except Exception:
        pass


def mark_converted(user: str | None = None) -> None:
    try:
        user = user or frappe.session.user
        for name in frappe.get_all("Hosting Abandoned Cart",
                                   filters={"user": user, "status": "Active"}, pluck="name"):
            frappe.db.set_value("Hosting Abandoned Cart", name, "status", "Converted")
    except Exception:
        pass


def process_abandoned_carts() -> dict:
    """Daily job: remind 1h/1d/7d, expire past final stage. Lock-guarded by scheduler."""
    now = now_datetime()
    stages = _stages()
    reminded, expired = [], []
    rows = frappe.get_all(
        "Hosting Abandoned Cart",
        filters={"status": "Active"},
        fields=["name", "user", "customer", "last_activity_at", "reminders_sent", "last_reminded_at"],
    )
    for row in rows:
        if not row.last_activity_at:
            continue
        due_stage = -1
        for i, hours in enumerate(stages):
            if add_to_date(row.last_activity_at, hours=hours) <= now and int(row.reminders_sent or 0) <= i:
                due_stage = i
        if due_stage < 0:
            if add_to_date(row.last_activity_at, hours=stages[-1] + 24) <= now:
                frappe.db.set_value("Hosting Abandoned Cart", row.name, "status", "Expired")
                expired.append(row.name)
            continue
        target = row.customer or row.user
        notify(target, "Your cart is waiting",
               f"Stage {due_stage + 1}/{len(stages)}: your hosting cart is still reserved. Check out to keep your selection.",
               "Hosting Abandoned Cart", row.name)
        frappe.db.set_value(
            "Hosting Abandoned Cart", row.name,
            {"reminders_sent": due_stage + 1, "last_reminded_at": now},
        )
        reminded.append(row.name)
    return {"reminded": reminded, "expired": expired}
