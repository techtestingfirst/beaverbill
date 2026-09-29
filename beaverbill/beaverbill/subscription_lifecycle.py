"""Phase 6 staff actions: retry, cancel, reinstate, override, purge.

Thin layer over the renewal engine in subscriptions.py.
"""

import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from beaverbill.beaverbill import billing
from beaverbill.beaverbill import settings as bb_settings
from beaverbill.beaverbill.subscription_support import notify_transition, require_staff, sync_services
from beaverbill.beaverbill.subscriptions import (
    PURGE_AFTER_TERMINATE_DAYS,
    STATES,
    handle_retry,
    transition,
    validate_transition,
)


def unused_credit(sub):
    start = getdate(sub.current_period_start or today())
    end = getdate(sub.current_period_end or sub.next_renewal_date or today())
    total_days = max((end - start).days + 1, 1)
    left = max((end - getdate(today())).days + 1, 0)
    return round(float(sub.amount or 0) * left / total_days, 2)


@frappe.whitelist()
def retry_subscription_payment(subscription_name: str) -> str:
    require_staff()
    sub = frappe.get_doc("Hosting Subscription", subscription_name)
    if sub.status not in ("Payment Failed", "Grace Period", "Renewal Pending"):
        frappe.throw(f"Subscription {sub.status} has nothing to retry", frappe.ValidationError)
    sub.next_retry_at = None
    sub.save()
    sub.reload()
    result = handle_retry(sub, now_datetime())
    if result != "renewed":
        frappe.throw(sub.last_error or "Retry did not collect payment", frappe.ValidationError)
    return sub.last_invoice or ""


@frappe.whitelist()
def cancel_subscription(subscription_name: str, mode: str = "end_of_period", reason: str = "") -> str:
    require_staff()
    if mode not in ("immediate", "end_of_period"):
        frappe.throw("mode must be immediate or end_of_period", frappe.ValidationError)
    sub = frappe.get_doc("Hosting Subscription", subscription_name)
    if sub.status in ("Terminated", "Archived"):
        frappe.throw(f"Subscription already {sub.status}", frappe.ValidationError)
    if mode == "end_of_period":
        previous = sub.status
        validate_transition(previous, "Cancellation Pending")
        sub.status = "Cancellation Pending"
        sub.cancel_at_period_end = 1
        sub.cancellation_mode = "End of Period"
        sub.cancellation_requested_at = now_datetime()
        sub.cancellation_effective_at = getdate(sub.current_period_end or sub.next_renewal_date)
        sub.save()
        notify_transition(sub, previous, "Cancellation Pending", reason or "End-of-period cancel")
        return sub.name
    credit = unused_credit(sub)
    previous = sub.status
    validate_transition(previous, "Terminated")
    sub.status = "Terminated"
    sub.cancellation_mode = "Immediate"
    sub.cancellation_requested_at = now_datetime()
    sub.cancellation_effective_at = getdate(today())
    sub.terminated_at = now_datetime()
    sub.data_purge_scheduled_at = add_days(
        today(), bb_settings.get_int("purge_after_terminate_days", PURGE_AFTER_TERMINATE_DAYS)
    )
    sub.save()
    if credit > 0:
        note = billing.create_credit_note(sub.customer, credit, reason=f"Unused period {sub.name}")
        billing.apply_credit_note(note.name)
    notify_transition(sub, previous, "Terminated", reason or f"Immediate cancel, credit {credit}")
    sync_services(sub)
    return sub.name


@frappe.whitelist()
def reinstate_subscription(subscription_name: str) -> str:
    require_staff()
    sub = frappe.get_doc("Hosting Subscription", subscription_name)
    if sub.status not in ("Cancellation Pending", "Suspended", "Grace Period", "Payment Failed"):
        frappe.throw(f"Subscription {sub.status} cannot be reinstated", frappe.ValidationError)
    previous = sub.status
    sub.status = "Active"
    sub.cancel_at_period_end = 0
    sub.cancellation_effective_at = None
    sub.retry_count = 0
    sub.next_retry_at = None
    sub.last_error = ""
    sub.suspend_reason = ""
    sub.reinstatement_count = int(sub.reinstatement_count or 0) + 1
    sub.save()
    notify_transition(sub, previous, "Active", "Reinstated by staff")
    sync_services(sub)
    return sub.name


@frappe.whitelist()
def override_subscription_state(subscription_name: str, to_state: str, reason: str = "") -> str:
    require_staff()
    if to_state not in STATES:
        frappe.throw(f"Unknown state {to_state}", frappe.ValidationError)
    transition(subscription_name, to_state, reason or "Staff override")
    return subscription_name


def purge_due(as_of=None):
    day = getdate(as_of) if as_of else getdate(today())
    return frappe.get_all(
        "Hosting Subscription",
        filters={"status": "Terminated", "data_purge_scheduled_at": ["<=", day]},
        pluck="name",
    )
