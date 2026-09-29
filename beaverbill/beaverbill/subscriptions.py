"""Phase 6 subscription engine: renewal, dunning, cancellation.

Old rows only knew Active/Suspended/Terminated and stay readable.
New states extend that set; old transitions remain legal.
"""

import frappe
from frappe.utils import add_days, add_months, getdate, now_datetime, today

from beaverbill.beaverbill import billing
from beaverbill.beaverbill import settings as bb_settings
from beaverbill.beaverbill.subscription_support import (
    acquire_lock,
    add_minutes_to_now,
    backoff_for,
    notify_transition,
    release_lock,
    sync_services,
)

STATES = (
    "Trial",
    "Active",
    "Renewal Pending",
    "Payment Failed",
    "Grace Period",
    "Suspended",
    "Cancellation Pending",
    "Terminated",
    "Archived",
)

TRANSITIONS = {
    "Trial": {"Active", "Cancellation Pending", "Terminated"},
    "Active": {"Renewal Pending", "Payment Failed", "Suspended", "Cancellation Pending", "Terminated"},
    "Renewal Pending": {"Active", "Payment Failed", "Grace Period", "Suspended", "Cancellation Pending", "Terminated"},
    "Payment Failed": {"Active", "Grace Period", "Suspended", "Cancellation Pending", "Terminated"},
    "Grace Period": {"Active", "Suspended", "Cancellation Pending", "Terminated"},
    "Suspended": {"Active", "Cancellation Pending", "Terminated", "Archived"},
    "Cancellation Pending": {"Active", "Terminated", "Archived"},
    "Terminated": {"Archived"},
    "Archived": set(),
}

CYCLE_MONTHS = {
    "Monthly": 1,
    "Quarterly": 3,
    "Semi-Annually": 6,
    "Annually": 12,
    "Biennially": 24,
    "Triennially": 36,
}

TERMINATE_AFTER_SUSPEND_DAYS = 14
PURGE_AFTER_TERMINATE_DAYS = 30


def _terminate_after_suspend_days() -> int:
	return bb_settings.get_int("terminate_after_suspend_days", TERMINATE_AFTER_SUSPEND_DAYS)


def _purge_after_terminate_days() -> int:
	return bb_settings.get_int("purge_after_terminate_days", PURGE_AFTER_TERMINATE_DAYS)


def _default_max_retries() -> int:
	return bb_settings.get_int("sub_default_max_retries", 4)


def _default_grace_days() -> int:
	return bb_settings.get_int("sub_default_grace_period_days", 7)


def _default_lead_days() -> int:
	return bb_settings.get_int("sub_default_renewal_lead_days", 3)


def validate_transition(previous, nxt):
    if previous == nxt:
        return
    if nxt not in TRANSITIONS.get(previous, set()):
        frappe.throw(
            f"Subscription cannot move from {previous} to {nxt}",
            frappe.ValidationError,
        )


def renewal_key(name, period_end):
    return f"renewal-{name}-{period_end}"


def months_for(cycle):
    return CYCLE_MONTHS.get(cycle or "Monthly", 1)


def advance_period(sub, from_date=None):
    base = getdate(from_date or sub.next_renewal_date or today())
    nxt = add_months(base, months_for(sub.billing_cycle))
    sub.current_period_start = base
    sub.current_period_end = add_days(nxt, -1)
    sub.next_renewal_date = nxt
    return nxt


def transition(name, to_state, note=""):
    sub = frappe.get_doc("Hosting Subscription", name)
    frappe.db.get_value("Hosting Subscription", name, "name", for_update=True)
    previous = sub.status
    validate_transition(previous, to_state)
    sub.status = to_state
    if to_state == "Suspended" and not sub.suspend_reason:
        sub.suspend_reason = note or "Suspended by scheduler"
    if to_state == "Terminated" and not sub.terminated_at:
        sub.terminated_at = now_datetime()
    sub.save()
    notify_transition(sub, previous, to_state, note)
    sync_services(sub)
    return sub


def try_autopay(sub, invoice):
    total = float(invoice.total_amount or 0)
    balance = billing.get_ledger_balance(sub.customer)
    if balance < total:
        return False
    billing.apply_credit_to_invoice(
        sub.customer, invoice.name, total, f"Auto-renewal for {sub.name}"
    )
    return True


def open_renewal_invoice(sub):
    period_end = getdate(sub.next_renewal_date)
    key = renewal_key(sub.name, period_end)
    existing = frappe.db.get_value("Hosting Invoice", {"idempotency_key": key}, "name")
    if existing:
        return frappe.get_doc("Hosting Invoice", existing)
    return billing.issue_invoice(
        sub.customer,
        [
            {
                "description": f"Renewal {sub.product} {sub.billing_cycle}",
                "product": sub.product,
                "qty": 1,
                "unit_price": float(sub.amount or 0),
                "line_total": float(sub.amount or 0),
                "billing_cycle": sub.billing_cycle,
            }
        ],
        due_date=period_end,
        currency=sub.currency or "USD",
        order=sub.order,
        idempotency_key=key,
        pricing_snapshot=None,
    )


def handle_due_renewal(sub, day):
    if not acquire_lock(sub):
        return "locked"
    try:
        sub.reload()
        if sub.status == "Trial" and sub.trial_end_date and getdate(sub.trial_end_date) <= day:
            transition(sub.name, "Active", "Trial ended")
            sub.reload()
        if sub.status not in ("Active", "Renewal Pending"):
            return "skipped"
        lead = int(sub.renewal_lead_days or _default_lead_days())
        if (getdate(sub.next_renewal_date) - day).days > lead and sub.status == "Active":
            return "not-due"
        if sub.status == "Active":
            sub.status = "Renewal Pending"
            sub.save()
            notify_transition(sub, "Active", "Renewal Pending", "Renewal window opened")
            sub.reload()
        if sub.cancel_at_period_end or sub.status == "Cancellation Pending":
            return "cancel-pending"
        invoice = open_renewal_invoice(sub)
        sub.db_set("last_invoice", invoice.name, update_modified=False)
        if try_autopay(sub, invoice):
            fresh = frappe.get_doc("Hosting Subscription", sub.name)
            advance_period(fresh, fresh.next_renewal_date)
            fresh.retry_count = 0
            fresh.next_retry_at = None
            fresh.last_error = ""
            fresh.status = "Active"
            fresh.save()
            notify_transition(fresh, "Renewal Pending", "Active", f"Renewed, invoice {invoice.name}")
            sync_services(fresh)
            return "renewed"
        fresh = frappe.get_doc("Hosting Subscription", sub.name)
        fresh.retry_count = int(fresh.retry_count or 0) + 1
        fresh.last_retry_at = now_datetime()
        fresh.next_retry_at = add_minutes_to_now(backoff_for(sub))
        fresh.last_error = f"Insufficient credit for invoice {invoice.name}"
        maxed = int(fresh.max_retries if fresh.max_retries is not None else _default_max_retries())
        grace = int(fresh.grace_period_days if fresh.grace_period_days is not None else _default_grace_days())
        if fresh.retry_count < maxed:
            fresh.status = "Payment Failed"
        elif grace <= 0:
            # Legacy rows with no dunning window suspend immediately.
            fresh.status = "Suspended"
            fresh.suspend_reason = fresh.last_error
        else:
            fresh.status = "Grace Period"
        fresh.save()
        notify_transition(fresh, "Renewal Pending", fresh.status, fresh.last_error)
        if fresh.status == "Suspended":
            sync_services(fresh)
        return "payment-failed"
    finally:
        release_lock(frappe.get_doc("Hosting Subscription", sub.name))


def handle_retry(sub, now):
    if sub.status != "Payment Failed":
        return "skipped"
    if sub.next_retry_at and sub.next_retry_at > now:
        return "not-due"
    invoice = (
        frappe.get_doc("Hosting Invoice", sub.last_invoice)
        if sub.last_invoice and frappe.db.exists("Hosting Invoice", sub.last_invoice)
        else open_renewal_invoice(sub)
    )
    if try_autopay(sub, invoice):
        fresh = frappe.get_doc("Hosting Subscription", sub.name)
        advance_period(fresh, fresh.next_renewal_date)
        fresh.retry_count = 0
        fresh.next_retry_at = None
        fresh.last_error = ""
        fresh.status = "Active"
        fresh.save()
        notify_transition(fresh, "Payment Failed", "Active", f"Retry paid invoice {invoice.name}")
        sync_services(fresh)
        return "renewed"
    fresh = frappe.get_doc("Hosting Subscription", sub.name)
    fresh.retry_count = int(fresh.retry_count or 0) + 1
    fresh.last_retry_at = now
    fresh.next_retry_at = add_minutes_to_now(backoff_for(sub))
    maxed = int(fresh.max_retries if fresh.max_retries is not None else _default_max_retries())
    nxt = "Payment Failed" if fresh.retry_count < maxed else "Grace Period"
    previous = fresh.status
    fresh.status = nxt
    fresh.last_error = f"Retry {fresh.retry_count} failed for invoice {invoice.name}"
    fresh.save()
    notify_transition(fresh, previous, nxt, fresh.last_error)
    return "payment-failed"


def handle_grace(sub, day):
    if sub.status != "Grace Period":
        return "skipped"
    window = int(sub.grace_period_days or _default_grace_days())
    anchor = getdate(sub.last_retry_at or sub.next_renewal_date or today())
    if (day - anchor).days < window:
        return "not-due"
    transition(sub.name, "Suspended", "Grace period expired")
    return "suspended"


def handle_suspended(sub, day):
    if sub.status != "Suspended":
        return "skipped"
    anchor = getdate(sub.last_retry_at or sub.next_renewal_date or today())
    if (day - anchor).days < _terminate_after_suspend_days():
        return "not-due"
    transition(sub.name, "Terminated", "Auto-terminated after suspension window")
    fresh = frappe.get_doc("Hosting Subscription", sub.name)
    fresh.termination_scheduled_at = today()
    fresh.data_purge_scheduled_at = add_days(today(), _purge_after_terminate_days())
    fresh.save()
    return "terminated"


def handle_cancellation_pending(sub, day):
    if sub.status != "Cancellation Pending":
        return "skipped"
    effective = sub.cancellation_effective_at
    if effective and getdate(effective) > day:
        return "not-due"
    transition(sub.name, "Terminated", "Cancellation effective date reached")
    fresh = frappe.get_doc("Hosting Subscription", sub.name)
    fresh.data_purge_scheduled_at = add_days(today(), _purge_after_terminate_days())
    fresh.save()
    return "terminated"


def process_subscription_renewals(as_of=None):
    day = getdate(as_of) if as_of else getdate(today())
    now = now_datetime()
    outcome = {"renewed": [], "payment-failed": [], "suspended": [], "terminated": []}
    names = frappe.get_all(
        "Hosting Subscription",
        filters={"status": ["in", list(TRANSITIONS)]},
        pluck="name",
    )
    for name in names:
        sub = frappe.get_doc("Hosting Subscription", name)
        if sub.status in ("Active", "Renewal Pending", "Trial"):
            result = handle_due_renewal(sub, day)
            if result == "renewed":
                outcome["renewed"].append(name)
            elif result == "payment-failed":
                outcome["payment-failed"].append(name)
        elif sub.status == "Payment Failed":
            if handle_retry(sub, now) == "renewed":
                outcome["renewed"].append(name)
            else:
                outcome["payment-failed"].append(name)
        elif sub.status == "Grace Period":
            if handle_grace(sub, day) == "suspended":
                outcome["suspended"].append(name)
        elif sub.status == "Suspended":
            if handle_suspended(sub, day) == "terminated":
                outcome["terminated"].append(name)
        elif sub.status == "Cancellation Pending":
            if handle_cancellation_pending(sub, day) == "terminated":
                outcome["terminated"].append(name)
    return outcome
