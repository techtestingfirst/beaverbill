"""Phase 10 portal: invoices, payment initiation, and payment status."""

import frappe

from beaverbill.beaverbill import billing as ledger
from beaverbill.beaverbill import gateways
from beaverbill.beaverbill.portal.guard import is_staff, own_invoice_or_throw, portal_customer, portal_endpoint


def _invoice_payload(doc) -> dict:
	return {
		"name": doc.name,
		"status": doc.status,
		"invoice_date": str(doc.invoice_date),
		"due_date": str(doc.due_date),
		"total_amount": float(doc.total_amount or 0),
		"paid_amount": float(doc.paid_amount or 0),
		"outstanding_amount": float(doc.outstanding_amount or 0),
		"currency": doc.currency,
		"items": [
			{"description": r.description, "qty": r.qty, "unit_price": float(r.unit_price or 0),
			 "line_total": float(r.line_total or 0)}
			for r in doc.items
		],
	}


@frappe.whitelist()
@portal_endpoint("portal.list_invoices", limit=60)
def list_invoices() -> dict:
	"""List the caller's invoices (both link styles)."""
	user = frappe.session.user
	customer = portal_customer()
	seen = {}
	for filt in ({"customer": user}, {"hosting_customer": customer}):
		for row in frappe.get_all(
			"Hosting Invoice",
			filters=filt,
			fields=["name", "invoice_date", "due_date", "status", "total_amount",
					"outstanding_amount", "currency"],
			order_by="creation desc",
		):
			seen[row.name] = row
	if is_staff(user):
		return {"invoices": list(seen.values())}
	rows = []
	for name in seen:
		try:
			own_invoice_or_throw(name, user)
			rows.append(seen[name])
		except frappe.PermissionError:
			continue
	return {"invoices": rows}


@frappe.whitelist()
@portal_endpoint("portal.get_invoice", limit=60)
def get_invoice(name: str) -> dict:
	"""Invoice detail (ownership enforced)."""
	return _invoice_payload(own_invoice_or_throw(name))


@frappe.whitelist()
@portal_endpoint("portal.invoice_pdf", limit=30)
def invoice_pdf(name: str) -> dict:
	"""Regenerate the invoice PDF and return its file URL."""
	doc = own_invoice_or_throw(name)
	stored = ledger.generate_invoice_pdf(doc.name)
	return {"invoice": doc.name, "pdf_url": stored.file_url}


@frappe.whitelist()
@portal_endpoint("portal.pay_invoice", limit=20)
def pay_invoice(invoice: str, gateway: str, payment_method: str | None = None,
				idempotency_key: str | None = None) -> dict:
	"""Create a server-side payment intent for the caller's invoice."""
	user = frappe.session.user
	doc = own_invoice_or_throw(invoice, user)
	if doc.status == "Paid":
		frappe.throw(f"Invoice {invoice} is already paid", frappe.ValidationError)
	intent = gateways.create_payment_intent(
		customer=doc.customer or user,
		invoice_name=doc.name,
		gateway_name=gateway,
		payment_method=payment_method,
		idempotency_key=idempotency_key or f"portal-pay-{doc.name}",
	)
	return {"payment": intent.name, "status": intent.status,
			"gateway_reference": intent.gateway_reference,
			"amount": float(intent.amount or 0), "currency": intent.currency}


@frappe.whitelist()
@portal_endpoint("portal.payment_status", limit=60)
def payment_status(payment: str) -> dict:
	"""Local payment status for the caller's transaction."""
	user = frappe.session.user
	doc = frappe.get_doc("Hosting Payment Transaction", payment)
	if not is_staff(user):
		customer = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
		inv = doc.source_invoice
		allowed = doc.customer == user
		if not allowed and inv:
			try:
				own_invoice_or_throw(inv, user)
				allowed = True
			except frappe.PermissionError:
				allowed = False
		if not allowed and customer:
			allowed = doc.customer == customer
		if not allowed:
			frappe.throw(f"Payment {payment} does not belong to this customer", frappe.PermissionError)
	return {"payment": doc.name, "status": doc.status, "amount": float(doc.amount or 0),
			"currency": doc.currency, "gateway": doc.gateway,
			"gateway_reference": doc.gateway_reference, "invoice": doc.source_invoice}
