"""Portal staff: fraud review queue and approve / reject."""

import frappe

from beaverbill.beaverbill import billing as ledger
from beaverbill.beaverbill import pricing
from beaverbill.beaverbill.notifications import billable_customer
from beaverbill.beaverbill.portal.guard import is_staff, portal_endpoint


def _require_staff():
    if not is_staff():
        frappe.throw("Only billing staff may review orders", frappe.PermissionError)


@frappe.whitelist()
@portal_endpoint("portal.list_reviews", limit=60)
def list_reviews() -> dict:
    """Held orders awaiting staff decision."""
    _require_staff()
    rows = frappe.get_all(
        "Hosting Order",
        filters={"status": ["in", ["Fraud Hold", "Manual Review"]]},
        fields=["name", "order_date", "status", "total_amount", "currency", "customer"],
        order_by="creation asc",
    )
    return {"reviews": rows}


@frappe.whitelist()
@portal_endpoint("portal.review_order", limit=20)
def review_order(order: str, action: str, note: str | None = None) -> dict:
    """Approve a held order into payment flow, or reject it."""
    _require_staff()
    if action not in ("approve", "reject"):
        frappe.throw("action must be approve or reject", frappe.ValidationError)
    doc = frappe.get_doc("Hosting Order", order)
    if doc.status not in ("Fraud Hold", "Manual Review"):
        frappe.throw(f"Order {order} is not awaiting review", frappe.ValidationError)
    log_name = frappe.db.get_value("Hosting Fraud Screening", {"order": order}, "name")
    if action == "reject":
        doc.status = "Cancelled"
        doc.cancellation_reason = (note or "Rejected on review")[:1000]
        doc.save()
        if log_name:
            frappe.db.set_value("Hosting Fraud Screening", log_name, "review_note", (note or "rejected")[:1000])
        return {"order": doc.name, "status": doc.status}
    customer = doc.hosting_customer
    is_first = True
    if doc.promo_code:
        try:
            pricing.redeem_promo(
                doc.promo_code,
                order_context={"is_first_order": is_first},
                customer=billable_customer(customer),
                order=doc.name,
                discount_given=sum(float(r.discount_amount or 0) for r in doc.items),
            )
        except frappe.ValidationError:
            pass
    doc.status = "Confirmed"
    doc.save()
    doc.status = "Payment Pending"
    doc.save()
    doc.reload()
    invoice = ledger.issue_invoice(
        billable_customer(customer),
        ledger.build_invoice_items(doc),
        currency=doc.currency,
        order=doc.name,
        idempotency_key=f"review-{doc.name}-invoice",
    )
    if log_name:
        frappe.db.set_value("Hosting Fraud Screening", log_name, "review_note", (note or "approved")[:1000])
        frappe.db.set_value("Hosting Fraud Screening", log_name, "reviewed_by", frappe.session.user)
    return {"order": doc.name, "status": doc.status, "invoice": invoice.name}
