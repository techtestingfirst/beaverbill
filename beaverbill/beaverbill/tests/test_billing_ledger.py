import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from beaverbill.beaverbill import billing


def wipe():
	for dt in [
		"Hosting Payment Allocation",
		"Hosting Payment Transaction",
		"Hosting Refund",
		"Hosting Credit Note",
		"Hosting Debit Note",
		"Hosting Invoice Item",
		"Hosting Invoice",
		"Customer Credit Transaction",
		"Hosting Order",
	]:
		for name in frappe.get_all(dt, pluck="name"):
			frappe.delete_doc(dt, name, ignore_permissions=True, force=True)


def ensure_user(email="phase4-buyer@example.com"):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Phase4", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return email


def ensure_product():
	if not frappe.db.exists("Hosting Product Group", "Phase4 Group"):
		frappe.get_doc({"doctype": "Hosting Product Group", "product_group_name": "Phase4 Group"}).insert()
	if not frappe.db.exists("Hosting Product", "Phase4 VPS"):
		frappe.get_doc(
			{
				"doctype": "Hosting Product",
				"product_name": "Phase4 VPS",
				"product_group": "Phase4 Group",
				"billing_cycle": "Monthly",
				"price": 100,
				"currency": "USD",
			}
		).insert()


def make_payment(customer, amount=100, status="Captured", key=None):
	return frappe.get_doc(
		{
			"doctype": "Hosting Payment Transaction",
			"customer": customer,
			"payment_date": today(),
			"amount": amount,
			"currency": "USD",
			"status": status,
			"idempotency_key": key or f"pay-{frappe.generate_hash(length=8)}",
		}
	).insert()


class TestBillingLedger(IntegrationTestCase):
	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.customer = ensure_user()
		ensure_product()

	def test_order_transitions(self):
		order = frappe.get_doc(
			{
				"doctype": "Hosting Order",
				"customer": self.customer,
				"order_date": today(),
				"status": "Draft",
				"currency": "USD",
				"total_amount": 10,
				"items": [{"product": "Phase4 VPS", "qty": 1, "price": 10, "total": 10}],
			}
		).insert()
		for nxt in ["Confirmed", "Payment Pending", "Paid", "Processing", "Completed"]:
			order.status = nxt
			order.save()
		order.reload()
		self.assertEqual(order.status, "Completed")
		order.status = "Paid"
		self.assertRaises(frappe.ValidationError, order.save)
		legacy = frappe.get_doc(
			{
				"doctype": "Hosting Order",
				"customer": self.customer,
				"order_date": today(),
				"status": "Pending",
				"currency": "USD",
				"total_amount": 5,
				"items": [{"product": "Phase4 VPS", "qty": 1, "price": 5, "total": 5}],
			}
		).insert()
		legacy.status = "Paid"
		legacy.save()
		self.assertEqual(legacy.status, "Paid")

	def test_issue_invoice_snapshot_and_freeze(self):
		inv = billing.issue_invoice(
			self.customer,
			[{"product": "Phase4 VPS", "description": "Phase4 VPS", "qty": 1, "unit_price": 100, "line_total": 100}],
			currency="USD",
		)
		self.assertEqual(inv.status, "Issued")
		self.assertEqual(len(inv.items), 1)
		self.assertTrue(inv.items[0].price_snapshot)
		self.assertEqual(float(inv.outstanding_amount), 100.0)
		inv.status = "Paid"
		inv.paid_amount = 100
		inv.save()
		inv.status = "Cancelled"
		self.assertRaises(frappe.ValidationError, inv.save)

	def test_full_and_partial_allocation(self):
		inv = billing.issue_invoice(
			self.customer,
			[{"description": "Two lines", "qty": 1, "unit_price": 200, "line_total": 200}],
		)
		pay = make_payment(self.customer, 200)
		billing.allocate_payment(pay.name, inv.name, amount=80, idempotency_key="alloc-p4-1")
		inv.reload()
		self.assertEqual(inv.status, "Partially Paid")
		self.assertEqual(float(inv.paid_amount), 80.0)
		billing.allocate_payment(pay.name, inv.name, amount=120, idempotency_key="alloc-p4-2")
		inv.reload()
		self.assertEqual(inv.status, "Paid")
		self.assertEqual(float(inv.outstanding_amount), 0.0)
		same = billing.allocate_payment(pay.name, inv.name, amount=120, idempotency_key="alloc-p4-2")
		self.assertEqual(same.idempotency_key, "alloc-p4-2")

	def test_over_allocation_throws(self):
		inv = billing.issue_invoice(self.customer, [{"description": "Small", "qty": 1, "unit_price": 50, "line_total": 50}])
		pay = make_payment(self.customer, 50)
		self.assertRaises(frappe.ValidationError, billing.allocate_payment, pay.name, inv.name, 60)

	def test_legacy_unpaid_invoice_still_allocates(self):
		inv = frappe.get_doc(
			{
				"doctype": "Hosting Invoice",
				"customer": self.customer,
				"invoice_date": today(),
				"due_date": today(),
				"status": "Unpaid",
				"total_amount": 40,
				"currency": "USD",
			}
		).insert()
		pay = make_payment(self.customer, 40)
		billing.allocate_payment(pay.name, inv.name)
		inv.reload()
		self.assertEqual(inv.status, "Paid")

	def test_credit_note_and_ledger(self):
		inv = billing.issue_invoice(self.customer, [{"description": "Note", "qty": 1, "unit_price": 100, "line_total": 100}])
		note = billing.create_credit_note(self.customer, 30, invoice=inv.name, reason="Goodwill", idempotency_key="cn-p4-1")
		billing.apply_credit_note(note.name, inv.name)
		inv.reload()
		self.assertEqual(inv.status, "Partially Paid")
		self.assertEqual(float(inv.paid_amount), 30.0)
		self.assertEqual(billing.get_ledger_balance(self.customer), 0.0)
		debit = billing.create_debit_note(self.customer, 10, invoice=inv.name, reason="Fee")
		self.assertEqual(debit.status, "Issued")
		note.reload()
		self.assertEqual(note.status, "Applied")

	def test_refund_posts_ledger_and_updates_payment(self):
		inv = billing.issue_invoice(self.customer, [{"description": "Refundable", "qty": 1, "unit_price": 90, "line_total": 90}])
		pay = make_payment(self.customer, 90)
		billing.allocate_payment(pay.name, inv.name)
		refund = billing.process_refund(self.customer, 90, payment=pay.name, invoice=inv.name, idempotency_key="ref-p4-1")
		self.assertEqual(refund.status, "Processed")
		pay.reload()
		self.assertEqual(pay.status, "Refunded")
		self.assertEqual(billing.get_ledger_balance(self.customer), 90.0)
		self.assertEqual(billing.ledger_mismatches(), [])

	def test_cancel_and_write_off_rules(self):
		inv = billing.issue_invoice(self.customer, [{"description": "Cancel me", "qty": 1, "unit_price": 20, "line_total": 20}])
		bad = frappe.get_doc("Hosting Invoice", inv.name)
		bad.status = "Cancelled"
		self.assertRaises(frappe.ValidationError, bad.save)
		billing.cancel_invoice(inv.name, "Duplicate")
		inv.reload()
		self.assertEqual(inv.status, "Cancelled")
		inv2 = billing.issue_invoice(self.customer, [{"description": "Write off", "qty": 1, "unit_price": 20, "line_total": 20}])
		billing.write_off_invoice(inv2.name, "Uncollectible")
		inv2.reload()
		self.assertEqual(inv2.status, "Written Off")

	def test_outstanding_report_and_overdue(self):
		inv = billing.issue_invoice(
			self.customer,
			[{"description": "Overdue", "qty": 1, "unit_price": 70, "line_total": 70}],
			due_date=add_days(today(), -5),
		)
		marked = billing.mark_overdue()
		self.assertIn(inv.name, marked)
		rows = billing.outstanding_invoices()
		self.assertTrue(any(r.name == inv.name for r in rows))

	def test_process_payment_compat(self):
		order = frappe.get_doc(
			{
				"doctype": "Hosting Order",
				"customer": self.customer,
				"order_date": today(),
				"status": "Pending",
				"currency": "USD",
				"total_amount": 10,
				"items": [{"product": "Phase4 VPS", "qty": 1, "price": 10, "total": 10}],
			}
		).insert()
		order.process_payment()
		self.assertEqual(order.status, "Paid")
		invoices = frappe.get_all("Hosting Invoice", filters={"order": order.name})
		self.assertEqual(len(invoices), 1)
