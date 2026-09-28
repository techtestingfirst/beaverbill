"""Phase 7 apply flow: effective times, driver resize, rollback, compensation."""

import json

import frappe
from frappe.utils import getdate, now_datetime, today

from beaverbill.beaverbill import billing
from beaverbill.beaverbill.modifications import (
    approve_modification,
    log_event,
    resize_service_resources,
)
from beaverbill.beaverbill.subscription_support import (
    notify_transition,
    require_staff,
    sync_services,
)


def _restore_subscription(sub, req):
    sub.product = req.old_product or sub.product
    sub.amount = req.old_amount if req.old_amount is not None else sub.amount
    sub.billing_cycle = req.old_billing_cycle or sub.billing_cycle
    sub.save()


def apply_modification(name, actor=None):
    req = frappe.get_doc("Hosting Service Modification Request", name)
    if req.status not in ("Approved", "Pending"):
        frappe.throw(f"Only Approved requests can be applied, not {req.status}", frappe.ValidationError)
    frappe.db.get_value("Hosting Service Modification Request", name, "name", for_update=True)
    req.reload()
    if req.status == "Pending":
        req = approve_modification(name)
        req.reload()
    sub = frappe.get_doc("Hosting Subscription", req.subscription)
    if float(req.proration_amount or 0) > 0:
        if not req.invoice:
            invoice = billing.issue_invoice(
                sub.customer,
                [{
                    "description": f"Upgrade {req.old_product or sub.product} to {req.new_product}",
                    "product": req.new_product,
                    "qty": 1,
                    "unit_price": float(req.proration_amount),
                    "line_total": float(req.proration_amount),
                    "billing_cycle": sub.billing_cycle,
                }],
                currency=sub.currency or "USD",
                order=sub.order,
                idempotency_key=f"{req.idempotency_key}-invoice",
            )
            req.invoice = invoice.name
            req.save()
        invoice = frappe.get_doc("Hosting Invoice", req.invoice)
        if invoice.status not in ("Paid",):
            frappe.throw(
                f"Upgrade invoice {invoice.name} is {invoice.status}; collect payment first",
                frappe.ValidationError,
            )
    previous_product = sub.product
    req.status = "Applying"
    log_event(req, "Apply Started", f"{previous_product} -> {req.new_product}", actor=actor)
    req.save()
    try:
        sub.product = req.new_product
        new_price = float((json.loads(req.new_product_snapshot or "{}") or {}).get("price", sub.amount))
        sub.amount = new_price
        sub.save()
        if req.service:
            try:
                svc = frappe.get_doc("Hosting Service", req.service)
                svc.status = "Modification Pending"
                svc.save(ignore_permissions=True)
            except frappe.ValidationError:
                pass
            resize_service_resources(req.service, req.new_product)
            log_event(req, "Resize Succeeded", req.new_product, actor=actor)
        req.status = "Completed"
        req.applied_at = now_datetime()
        if float(req.proration_amount or 0) < 0 and not req.credit_transaction:
            credit = billing.post_ledger(
                sub.customer,
                abs(float(req.proration_amount)),
                "Credit",
                f"Prorated downgrade credit for {req.name}",
                "Hosting Service Modification Request",
                req.name,
                idempotency_key=f"{req.idempotency_key}-credit",
            )
            req.credit_transaction = credit.name
        log_event(req, "Completed", f"{previous_product} -> {req.new_product}", actor=actor)
        req.save()
        notify_transition(sub, previous_product, req.new_product, f"Modification {req.name} completed")
        return req
    except Exception as exc:
        req.reload()
        sub.reload()
        _restore_subscription(sub, req)
        if req.invoice and frappe.db.exists("Hosting Invoice", req.invoice):
            invoice = frappe.get_doc("Hosting Invoice", req.invoice)
            if invoice.status in ("Issued", "Partially Paid", "Overdue", "Unpaid"):
                billing.cancel_invoice(invoice.name, f"Modification {req.name} resize failed")
        req.status = "Failed"
        req.failure_reason = str(exc)[:1000]
        log_event(req, "Resize Failed", str(exc)[:1000], actor=actor)
        log_event(req, "Rolled Back", f"restored {previous_product}", actor=actor)
        req.save()
        if req.service and frappe.db.exists("Hosting Service", req.service):
            sync_services(sub)
        raise


def compensate_modification(name, actor=None):
    require_staff()
    req = frappe.get_doc("Hosting Service Modification Request", name)
    if req.status != "Failed":
        frappe.throw(f"Only Failed requests can be compensated, not {req.status}", frappe.ValidationError)
    sub = frappe.get_doc("Hosting Subscription", req.subscription)
    if req.invoice and frappe.db.exists("Hosting Invoice", req.invoice):
        invoice = frappe.get_doc("Hosting Invoice", req.invoice)
        if invoice.status == "Paid":
            note = billing.create_credit_note(
                sub.customer,
                float(invoice.total_amount or 0),
                reason=f"Compensation for failed modification {req.name} (invoice {invoice.name})",
                idempotency_key=f"{req.idempotency_key}-compensation",
            )
            billing.apply_credit_note(note.name)
    else:
        billing.post_ledger(
            sub.customer,
            abs(float(req.proration_amount or 0)),
            "Credit",
            f"Compensation for failed modification {req.name}",
            "Hosting Service Modification Request",
            req.name,
            idempotency_key=f"{req.idempotency_key}-compensation",
        )
    req.status = "Compensated"
    log_event(req, "Compensated", "customer credited back", actor=actor)
    req.save()
    return req


@frappe.whitelist()
def retry_modification(name):
    require_staff()
    req = frappe.get_doc("Hosting Service Modification Request", name)
    if req.status != "Failed":
        frappe.throw("Only Failed requests can be retried", frappe.ValidationError)
    req.status = "Approved"
    req.failure_reason = ""
    log_event(req, "Approved", "retry after failure")
    req.save()
    return apply_modification(name, actor=frappe.session.user).name


def apply_due_modifications(as_of=None):
    day = getdate(as_of) if as_of else getdate(today())
    applied = []
    for name in frappe.get_all(
        "Hosting Service Modification Request",
        filters={"status": "Approved", "effective_mode": "Next Cycle", "effective_date": ["<=", day]},
        pluck="name",
    ):
        try:
            apply_modification(name, actor="scheduler")
            applied.append(name)
        except Exception:
            continue
    return applied
