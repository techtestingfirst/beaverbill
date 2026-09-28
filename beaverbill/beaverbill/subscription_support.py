"""Phase 6 shared helpers: locks, notifications, service sync.

Kept separate so the renewal engine and staff actions stay small.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

LOCK_TIMEOUT_MINUTES = 10


def require_staff():
    roles = set(frappe.get_roles(frappe.session.user))
    if not roles & {"System Manager", "Hosting Admin"}:
        frappe.throw("Only billing staff may run this action", frappe.PermissionError)


def backoff_for(sub):
    base = int(sub.retry_backoff_minutes or 240)
    count = int(sub.retry_count or 0) + 1
    return base * (2 ** (count - 1))


def add_minutes_to_now(minutes):
    return add_to_date(now_datetime(), minutes=int(minutes))


def notify_transition(sub, previous, nxt, note=""):
    try:
        frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Hosting Subscription",
                "reference_name": sub.name,
                "content": f"Subscription {previous} -> {nxt}. {note or ''}".strip(),
            }
        ).insert(ignore_permissions=True)
    except Exception:
        pass
    try:
        email = sub.customer if "@" in (sub.customer or "") else None
        if email:
            frappe.sendmail(
                recipients=[email],
                subject=f"Subscription {sub.name} is now {nxt}",
                message=f"Your subscription moved from {previous} to {nxt}. {note or ''}".strip(),
            )
    except Exception:
        pass


def sync_services(sub):
    mapping = {
        "Suspended": "Suspended",
        "Terminated": "Terminated",
        "Archived": "Archived",
        "Active": "Active",
    }
    target = mapping.get(sub.status)
    if not target:
        return []
    updated = []
    for row in frappe.get_all("Hosting Service", filters={"subscription": sub.name}, pluck="name"):
        svc = frappe.get_doc("Hosting Service", row)
        if svc.status == target:
            continue
        try:
            svc.status = target
            svc.save(ignore_permissions=True)
            updated.append(row)
        except Exception:
            continue
    return updated


def acquire_lock(sub):
    locked_at = sub.locked_at
    if locked_at:
        age = (now_datetime() - locked_at).total_seconds() / 60
        if age < LOCK_TIMEOUT_MINUTES:
            return False
    sub.locked_at = now_datetime()
    sub.locked_by = "scheduler"
    sub.db_set("locked_at", sub.locked_at, update_modified=False)
    sub.db_set("locked_by", "scheduler", update_modified=False)
    sub.reload()
    return True


def release_lock(sub):
    sub.db_set("locked_at", None, update_modified=False)
    sub.db_set("locked_by", None, update_modified=False)
