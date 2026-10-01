"""Phase 4 billing ledger: invoices, allocations, credits, refunds, reports.

Old wallet behavior stays readable: balances still sum `amount` rows.
New code also stores `balance_after` on each ledger row.
"""

import json
import uuid

import frappe
from frappe.utils import getdate, today

from beaverbill.beaverbill import settings as bb_settings


def _default_currency() -> str:
	return bb_settings.get_str("default_currency", "USD")


def _key(value=None):
	return value or f"bb-{uuid.uuid4().hex[:12]}"


def _invoice_totals(items):
	subtotal = sum(float(i.get("line_total") or 0) for i in items)
	return subtotal


def issue_invoice(customer, items, due_date=None, currency=None, order=None, idempotency_key=None, pricing_snapshot=None):
	"""Create a Draft invoice with frozen line snapshots, then Issue it."""
	currency = currency or _default_currency()
	if idempotency_key:
		existing = frappe.db.get_value("Hosting Invoice", {"idempotency_key": idempotency_key}, "name")
		if existing:
			return frappe.get_doc("Hosting Invoice", existing)
	lines = []
	for row in items:
		lines.append(
			{
				"description": row.get("description") or row.get("product") or "Line",
				"product": row.get("product"),
				"qty": row.get("qty") or 1,
				"unit_price": row.get("unit_price") or 0,
				"discount_amount": row.get("discount_amount") or 0,
				"tax_amount": row.get("tax_amount") or 0,
				"line_total": row.get("line_total") or 0,
				"billing_cycle": row.get("billing_cycle"),
				"price_snapshot": json.dumps(row, default=str)[:4000],
			}
		)
	total = _invoice_totals(lines)
	doc = frappe.get_doc(
		{
			"doctype": "Hosting Invoice",
			"customer": customer,
			"invoice_date": today(),
			"due_date": due_date or today(),
			"status": "Draft",
			"total_amount": total,
			"paid_amount": 0,
			"outstanding_amount": total,
			"currency": currency,
			"order": order,
			"items": lines,
			"pricing_snapshot": pricing_snapshot or json.dumps({"items": lines}, default=str),
			"idempotency_key": _key(idempotency_key),
		}
	).insert()
	doc.status = "Issued"
	doc.save()
	return doc


def _locked(doctype, name):
	return frappe.db.get_value(doctype, name, ["name", "status"], for_update=True)


def allocate_payment(payment_name, invoice_name, amount=None, idempotency_key=None, ignore_permissions=False):
	"""Allocate a captured payment to an invoice. Supports partial amounts."""
	if idempotency_key:
		existing = frappe.db.get_value("Hosting Payment Allocation", {"idempotency_key": idempotency_key}, "name")
		if existing:
			return frappe.get_doc("Hosting Payment Allocation", existing)
	payment = frappe.get_doc("Hosting Payment Transaction", payment_name)
	invoice = frappe.get_doc("Hosting Invoice", invoice_name)
	_locked("Hosting Invoice", invoice_name)
	_locked("Hosting Payment Transaction", payment_name)
	if payment.status not in ("Captured", "Authorized", "Partially Refunded"):
		frappe.throw(f"Payment {payment.status} cannot be allocated", frappe.ValidationError)
	outstanding = float(invoice.total_amount or 0) - float(invoice.paid_amount or 0)
	take = float(amount) if amount is not None else outstanding
	if take <= 0 or take - outstanding > 0.005:
		frappe.throw(f"Allocation {take} exceeds outstanding {outstanding}", frappe.ValidationError)
	allocation = frappe.get_doc(
		{
			"doctype": "Hosting Payment Allocation",
			"payment": payment_name,
			"invoice": invoice_name,
			"allocated_amount": take,
			"allocation_date": today(),
			"idempotency_key": _key(idempotency_key),
		}
	)
	if ignore_permissions:
		# Provider callbacks run in the payer's session, which owns no
		# allocation rights. Amounts were fixed server-side at intent time.
		allocation.flags.ignore_permissions = True
	allocation.insert()
	paid = float(invoice.paid_amount or 0) + take
	invoice.paid_amount = paid
	invoice.outstanding_amount = float(invoice.total_amount or 0) - paid
	if invoice.outstanding_amount <= 0.005:
		invoice.status = "Paid"
	else:
		invoice.status = "Partially Paid"
	invoice.save()
	return allocation


def get_ledger_balance(customer):
	rows = frappe.get_all("Customer Credit Transaction", filters={"customer": customer}, fields=["amount"])
	return sum(float(r.amount or 0) for r in rows)


def post_ledger(customer, amount, entry_type, description="", source_type=None, source_name=None, idempotency_key=None):
	"""Append one signed ledger row with running balance. Idempotent."""
	if idempotency_key:
		existing = frappe.db.get_value("Customer Credit Transaction", {"idempotency_key": idempotency_key}, "name")
		if existing:
			return frappe.get_doc("Customer Credit Transaction", existing)
	balance = get_ledger_balance(customer)
	doc = frappe.get_doc(
		{
			"doctype": "Customer Credit Transaction",
			"customer": customer,
			"transaction_date": today(),
			"amount": amount,
			"type": entry_type,
			"balance_after": balance + float(amount or 0),
			"description": description,
			"source_type": source_type,
			"source_name": source_name,
			"idempotency_key": _key(idempotency_key),
		}
	).insert()
	return doc


def apply_credit_to_invoice(customer, invoice_name, amount, description="Credit applied"):
	"""Reduce invoice outstanding with a ledger-backed credit."""
	invoice = frappe.get_doc("Hosting Invoice", invoice_name)
	_locked("Hosting Invoice", invoice_name)
	outstanding = float(invoice.total_amount or 0) - float(invoice.paid_amount or 0)
	if float(amount) <= 0 or float(amount) - outstanding > 0.005:
		frappe.throw("Credit exceeds invoice outstanding", frappe.ValidationError)
	post_ledger(customer, -float(amount), "Debit", description, "Hosting Invoice", invoice_name)
	paid = float(invoice.paid_amount or 0) + float(amount)
	invoice.paid_amount = paid
	invoice.outstanding_amount = float(invoice.total_amount or 0) - paid
	invoice.status = "Paid" if invoice.outstanding_amount <= 0.005 else "Partially Paid"
	invoice.save()
	return invoice


def create_credit_note(customer, amount, invoice=None, reason="", idempotency_key=None):
	if idempotency_key:
		existing = frappe.db.get_value("Hosting Credit Note", {"idempotency_key": idempotency_key}, "name")
		if existing:
			return frappe.get_doc("Hosting Credit Note", existing)
	return frappe.get_doc(
		{
			"doctype": "Hosting Credit Note",
			"customer": customer,
			"invoice": invoice,
			"credit_date": today(),
			"amount": amount,
			"status": "Issued",
			"reason": reason,
			"idempotency_key": _key(idempotency_key),
		}
	).insert()


def apply_credit_note(note_name, invoice_name=None):
	note = frappe.get_doc("Hosting Credit Note", note_name)
	if note.status not in ("Issued",):
		frappe.throw(f"Credit note {note.status} cannot be applied", frappe.ValidationError)
	target = invoice_name or note.invoice
	post_ledger(note.customer, float(note.amount), "Credit", f"Credit note {note.name}", "Hosting Credit Note", note.name)
	if target:
		apply_credit_to_invoice(note.customer, target, float(note.amount), f"Credit note {note.name}")
	note.status = "Applied"
	note.save()
	return note


def create_debit_note(customer, amount, invoice=None, reason="", idempotency_key=None):
	if idempotency_key:
		existing = frappe.db.get_value("Hosting Debit Note", {"idempotency_key": idempotency_key}, "name")
		if existing:
			return frappe.get_doc("Hosting Debit Note", existing)
	return frappe.get_doc(
		{
			"doctype": "Hosting Debit Note",
			"customer": customer,
			"invoice": invoice,
			"debit_date": today(),
			"amount": amount,
			"status": "Issued",
			"reason": reason,
			"idempotency_key": _key(idempotency_key),
		}
	).insert()


def process_refund(customer, amount, payment=None, invoice=None, reason="", idempotency_key=None):
	if idempotency_key:
		existing = frappe.db.get_value("Hosting Refund", {"idempotency_key": idempotency_key}, "name")
		if existing:
			return frappe.get_doc("Hosting Refund", existing)
	refund = frappe.get_doc(
		{
			"doctype": "Hosting Refund",
			"customer": customer,
			"payment": payment,
			"invoice": invoice,
			"refund_date": today(),
			"amount": amount,
			"status": "Processed",
			"reason": reason,
			"idempotency_key": _key(idempotency_key),
		}
	).insert()
	post_ledger(customer, float(amount), "Credit", f"Refund {refund.name}", "Hosting Refund", refund.name)
	if payment:
		pay = frappe.get_doc("Hosting Payment Transaction", payment)
		pay.status = "Refunded" if pay.status == "Captured" else "Partially Refunded"
		pay.save()
	return refund


def cancel_invoice(invoice_name, reason):
	invoice = frappe.get_doc("Hosting Invoice", invoice_name)
	if invoice.status in ("Paid", "Written Off"):
		frappe.throw(f"A {invoice.status} invoice cannot be cancelled", frappe.ValidationError)
	invoice.cancellation_reason = reason
	invoice.status = "Cancelled"
	invoice.save()
	return invoice


def write_off_invoice(invoice_name, reason):
	invoice = frappe.get_doc("Hosting Invoice", invoice_name)
	if invoice.status in ("Paid", "Cancelled", "Written Off"):
		frappe.throw(f"A {invoice.status} invoice cannot be written off", frappe.ValidationError)
	invoice.reversal_reason = reason
	invoice.status = "Written Off"
	invoice.save()
	return invoice


def generate_invoice_pdf(invoice_name):
	"""Render the invoice print view to a real PDF File and link it. Returns the File doc."""
	invoice = frappe.get_doc("Hosting Invoice", invoice_name)
	html = frappe.get_print("Hosting Invoice", invoice_name, "Standard")
	from frappe.utils.file_manager import save_file
	from frappe.utils.pdf import get_pdf

	pdf_bytes = get_pdf(html)
	stored = save_file(f"{invoice_name}.pdf", pdf_bytes, "Hosting Invoice", invoice_name, is_private=1)
	invoice.invoice_pdf = stored.file_url
	invoice.save()
	return stored


def outstanding_invoices():
	return frappe.db.sql(
		"""select name, customer, total_amount, paid_amount,
			(total_amount - ifnull(paid_amount, 0)) as outstanding, status, due_date
			from `tabHosting Invoice`
			where status in ('Issued', 'Partially Paid', 'Overdue', 'Unpaid')
			order by due_date""",
		as_dict=True,
	)


def ledger_mismatches():
	"""Rows where stored balance_after differs from the running sum."""
	entries = frappe.db.sql(
		"""select name, customer, amount, balance_after, creation
			from `tabCustomer Credit Transaction` order by customer, creation, name""",
		as_dict=True,
	)
	bad = []
	running = {}
	for row in entries:
		key = row.customer
		running[key] = running.get(key, 0.0) + float(row.amount or 0)
		if row.balance_after is not None and abs(float(row.balance_after) - running[key]) > 0.005:
			bad.append(row.name)
	return bad


def mark_overdue(as_of=None):
	day = getdate(as_of) if as_of else getdate(today())
	rows = frappe.get_all(
		"Hosting Invoice",
		filters={"status": ["in", ["Issued", "Partially Paid"]], "due_date": ["<", day]},
		pluck="name",
	)
	for name in rows:
		doc = frappe.get_doc("Hosting Invoice", name)
		doc.status = "Overdue"
		doc.save()
	return rows
