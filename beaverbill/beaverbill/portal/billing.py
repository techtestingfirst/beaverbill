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


def _own_payment_method(name: str, user=None) -> object:
	user = user or frappe.session.user
	doc = frappe.get_doc("Hosting Payment Method", name)
	if is_staff(user):
		return doc
	if doc.customer != user:
		frappe.throw(f"Payment method {name} does not belong to this customer", frappe.PermissionError)
	return doc


@frappe.whitelist()
@portal_endpoint("portal.list_payment_methods", limit=60)
def list_payment_methods() -> dict:
	"""Tokenized payment methods for the caller. Raw card data is never stored."""
	user = frappe.session.user
	portal_customer()
	rows = frappe.get_all(
		"Hosting Payment Method",
		filters={"customer": user},
		fields=["name", "gateway", "brand", "last4", "exp_month", "exp_year", "is_default"],
		order_by="creation desc",
	)
	return {"methods": rows}


@frappe.whitelist()
@portal_endpoint("portal.add_payment_method", limit=10)
def add_payment_method(gateway: str, token_reference: str, brand: str | None = None,
					   last4: str | None = None, exp_month: str | None = None,
					   exp_year: str | None = None, make_default: bool = False) -> dict:
	"""Save a gateway-issued token reference. PANs and CVVs are always refused."""
	user = frappe.session.user
	portal_customer()
	if not token_reference or len(token_reference.strip()) < 4:
		frappe.throw("A gateway token reference is required", frappe.ValidationError)
	joined = " ".join([token_reference, brand or "", last4 or ""]).lower()
	if any(marker in joined for marker in ("4111", "4242", "cvv", "cvc")):
		frappe.throw("Raw card data must never be sent to this API", frappe.ValidationError)
	if last4 and (len(last4) != 4 or not last4.isdigit()):
		frappe.throw("last4 must be exactly four digits", frappe.ValidationError)
	doc = frappe.get_doc(
		{
			"doctype": "Hosting Payment Method",
			"customer": user,
			"gateway": gateway,
			"token_reference": token_reference.strip(),
			"brand": (brand or "")[:40],
			"last4": (last4 or "")[:4],
			"exp_month": (exp_month or "")[:2],
			"exp_year": (exp_year or "")[:4],
			"is_default": 1 if make_default else 0,
		}
	).insert()
	if make_default:
		for row in frappe.get_all("Hosting Payment Method",
								  filters={"customer": user, "name": ("!=", doc.name)}, pluck="name"):
			frappe.db.set_value("Hosting Payment Method", row, "is_default", 0)
	return {"method": doc.name}


@frappe.whitelist()
@portal_endpoint("portal.remove_payment_method", limit=10)
def remove_payment_method(name: str) -> dict:
	"""Delete the caller's saved method (the gateway token itself is unaffected)."""
	doc = _own_payment_method(name)
	doc.delete()
	return {"deleted": name}


@frappe.whitelist()
@portal_endpoint("portal.list_gateways", limit=60)
def list_gateways(currency: str | None = None) -> dict:
	"""Payment gateways the caller may pay through, optionally filtered by currency."""
	user = frappe.session.user
	portal_customer()
	rows = frappe.get_all(
		"Hosting Payment Gateway",
		filters={"is_active": 1},
		fields=["name", "provider", "supported_currencies", "default_currency"],
		order_by="name asc",
	)
	items = []
	for row in rows:
		if is_staff(user):
			items.append(row)
			continue
		currencies = [c.strip().upper() for c in (row.supported_currencies or "").split(",") if c.strip()]
		if currency and currency.upper() not in currencies:
			continue
		items.append({"name": row.name, "provider": row.provider,
					  "supported_currencies": row.supported_currencies,
					  "default_currency": row.default_currency})
	return {"gateways": items}
