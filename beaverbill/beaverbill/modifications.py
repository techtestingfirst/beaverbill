"""Phase 7 modification engine: snapshots, proration, effective times, rollback.

Legacy controller math for Monthly/Quarterly/Semi-Annually/Annually and
past-due inputs is preserved byte-for-byte; the engine extends it to
Biennially/Triennially (the old code fell back to one month there).
"""

import json

import frappe
from frappe.utils import add_days, add_months, date_diff, getdate, now_datetime, today

from beaverbill.beaverbill import billing
from beaverbill.beaverbill.subscription_support import (
    notify_transition,
    require_staff,
    sync_services,
)

CYCLE_MONTHS = {
    "Monthly": 1,
    "Quarterly": 3,
    "Semi-Annually": 6,
    "Annually": 12,
    "Biennially": 24,
    "Triennially": 36,
}

OPEN_STATUSES = ("Pending", "Approved", "Applying")
POLICY_STATUSES = ("Trial", "Active", "Renewal Pending")
SPEC_FIELDS = ("cpu_cores", "ram_mb", "disk_gb", "bandwidth_gb")


def compute_proration(sub, new_price, as_of=None):
    day = getdate(as_of) if as_of else getdate(today())
    renewal = getdate(sub.next_renewal_date)
    if renewal <= day:
        return round(float(new_price), 2)
    months = CYCLE_MONTHS.get(sub.billing_cycle, 1)
    start = add_months(renewal, -months)
    total = date_diff(renewal, start) or 30
    ratio = float(date_diff(renewal, day)) / float(total)
    return round(float(new_price) * ratio - float(sub.amount) * ratio, 2)


def snapshot_product(name):
    doc = frappe.get_doc("Hosting Product", name)
    return {
        "name": doc.name,
        "price": float(doc.price or 0),
        "billing_cycle": doc.billing_cycle,
        "currency": doc.currency,
        **{f: int(doc.get(f) or 0) for f in SPEC_FIELDS},
    }


def log_event(req, action, detail="", actor=None):
    req.append(
        "events",
        {
            "timestamp": now_datetime(),
            "action": action,
            "actor": actor or frappe.session.user,
            "detail": (detail or "")[:1000],
        },
    )


def freeze_snapshots(req):
    sub = frappe.get_doc("Hosting Subscription", req.subscription)
    req.old_product = sub.product
    req.old_amount = sub.amount
    req.old_billing_cycle = sub.billing_cycle
    req.old_product_snapshot = json.dumps(snapshot_product(sub.product), default=str)
    req.new_product_snapshot = json.dumps(snapshot_product(req.new_product), default=str)
    if req.service:
        svc = frappe.get_doc("Hosting Service", req.service)
        req.usage_snapshot = svc.upstream_metadata or "{}"
    log_event(req, "Snapshots Frozen", f"{req.old_product} -> {req.new_product}")


def downgrade_warnings_for(old_spec, new_spec):
    warnings = []
    for field in SPEC_FIELDS:
        old, new = int(old_spec.get(field) or 0), int(new_spec.get(field) or 0)
        if old > 0 and 0 < new < old:
            warnings.append(f"{field} shrinks from {old} to {new}")
        elif old > 0 and new == 0 and any(int(new_spec.get(f) or 0) > 0 for f in SPEC_FIELDS):
            warnings.append(f"{field} becomes unspecified from {old}")
    return warnings


def check_downgrade_usage(service_name, new_spec):
    """Block a downgrade that would strand recorded usage."""
    svc = frappe.get_doc("Hosting Service", service_name)
    try:
        usage = json.loads(svc.upstream_metadata or "{}").get("usage", {})
    except ValueError:
        usage = {}
    blocking = []
    for field in SPEC_FIELDS:
        used = usage.get(field, usage.get(field + "_used", 0)) or 0
        cap = int(new_spec.get(field) or 0)
        if cap > 0 and float(used) > cap:
            blocking.append(f"recorded usage {field}={used} exceeds new product cap {cap}")
    return blocking


def check_policy(sub):
    if sub.status not in POLICY_STATUSES:
        frappe.throw(
            f"Modifications need a {', '.join(POLICY_STATUSES)} subscription, not {sub.status}",
            frappe.ValidationError,
        )
    if sub.cancel_at_period_end or sub.status == "Cancellation Pending":
        frappe.throw("A subscription pending cancellation cannot be modified", frappe.ValidationError)


def open_request(subscription_name):
    return frappe.get_all(
        "Hosting Service Modification Request",
        filters={"subscription": subscription_name, "status": ["in", list(OPEN_STATUSES)]},
        pluck="name",
    )


def request_modification(subscription_name, new_product, effective_mode="Immediate",
                         service=None, data_loss_acknowledged=False, idempotency_key=None):
    if idempotency_key:
        existing = frappe.db.get_value(
            "Hosting Service Modification Request", {"idempotency_key": idempotency_key}, "name"
        )
        if existing:
            return frappe.get_doc("Hosting Service Modification Request", existing)
    if effective_mode not in ("Immediate", "Next Cycle"):
        frappe.throw("effective_mode must be Immediate or Next Cycle", frappe.ValidationError)
    frappe.db.get_value("Hosting Subscription", subscription_name, "name", for_update=True)
    sub = frappe.get_doc("Hosting Subscription", subscription_name)
    check_policy(sub)
    if sub.product == new_product:
        frappe.throw("New product must differ from the current product", frappe.ValidationError)
    if open_request(subscription_name):
        frappe.throw("A modification is already in progress for this subscription", frappe.ValidationError)
    old_spec, new_spec = snapshot_product(sub.product), snapshot_product(new_product)
    warnings = downgrade_warnings_for(old_spec, new_spec) if float(new_spec["price"]) < float(old_spec["price"]) else []
    if service:
        blocking = check_downgrade_usage(service, new_spec)
        if blocking:
            frappe.throw("Downgrade blocked: " + "; ".join(blocking), frappe.ValidationError)
    if warnings and not data_loss_acknowledged:
        frappe.throw(
            "Downgrade may lose capacity (" + "; ".join(warnings) + "). Resubmit with data_loss_acknowledged.",
            frappe.ValidationError,
        )
    req = frappe.get_doc(
        {
            "doctype": "Hosting Service Modification Request",
            "subscription": subscription_name,
            "service": service,
            "new_product": new_product,
            "status": "Pending",
            "effective_mode": effective_mode,
            "effective_date": today()
            if effective_mode == "Immediate"
            else getdate(sub.current_period_end or sub.next_renewal_date),
            "proration_amount": compute_proration(sub, new_spec["price"]),
            "idempotency_key": idempotency_key or f"mod-{frappe.generate_hash(length=12)}",
            "downgrade_warnings": "\n".join(warnings),
            "data_loss_acknowledged": 1 if warnings and data_loss_acknowledged else 0,
        }
    ).insert()
    freeze_snapshots(req)
    log_event(req, "Created", f"mode={effective_mode} proration={req.proration_amount}")
    log_event(req, "Proration Calculated", str(req.proration_amount))
    req.save()
    return req


def approve_modification(name):
    req = frappe.get_doc("Hosting Service Modification Request", name)
    if req.status == "Approved":
        return req
    if req.status != "Pending":
        frappe.throw(f"Only Pending requests can be approved, not {req.status}", frappe.ValidationError)
    frappe.db.get_value("Hosting Service Modification Request", name, "name", for_update=True)
    req.reload()
    sub = frappe.get_doc("Hosting Subscription", req.subscription)
    check_policy(sub)
    req.status = "Approved"
    if req.effective_mode == "Immediate" and float(req.proration_amount or 0) > 0:
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
    log_event(req, "Approved", f"invoice={req.invoice or 'deferred'}")
    req.save()
    return req


def resize_service_resources(service_name, new_product_name):
    svc = frappe.get_doc("Hosting Service", service_name)
    driver_type = None
    if svc.provider_account:
        driver_type = frappe.db.get_value("Hosting Provider Account", svc.provider_account, "provider_type")
    from beaverbill.beaverbill.provisioning_drivers import get_provisioning_driver

    if not driver_type or driver_type == "Custom":
        frappe.logger().info(f"Provisioning: Resized subscription service {service_name} to {new_product_name}")
        return {"status": "Success", "simulated": True}
    return get_provisioning_driver(driver_type).resize(svc.subscription or service_name, new_product_name)
