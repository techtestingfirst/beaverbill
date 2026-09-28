import hashlib
import hmac
import json

import frappe
from frappe.tests import IntegrationTestCase

from beaverbill.beaverbill import billing
from beaverbill.beaverbill import gateways
from beaverbill.beaverbill import webhooks
from beaverbill.beaverbill.gateways import GatewayOutage
from beaverbill.beaverbill.webhooks import SchemaError

SECRET = "phase5-test-secret"


def wipe():
	for dt in [
		"Hosting Payment Event",
		"Hosting Payment Method",
		"Hosting Payment Allocation",
		"Hosting Payment Transaction",
		"Hosting Refund",
		"Hosting Invoice Item",
		"Hosting Invoice",
		"Customer Credit Transaction",
		"Hosting Payment Gateway",
	]:
		for name in frappe.get_all(dt, pluck="name"):
			frappe.delete_doc(dt, name, ignore_permissions=True, force=True)


def ensure_user(email="phase5-buyer@example.com"):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Phase5", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return email


def ensure_gateway(name="Phase5 Gateway", provider="Test Gateway", maintenance=False):
	if frappe.db.exists("Hosting Payment Gateway", name):
		doc = frappe.get_doc("Hosting Payment Gateway", name)
		doc.maintenance_mode = 1 if maintenance else 0
		doc.save()
		return doc
	return frappe.get_doc(
		{
			"doctype": "Hosting Payment Gateway",
			"gateway_name": name,
			"provider": provider,
			"supported_currencies": "USD,INR",
			"default_currency": "USD",
			"webhook_secret": SECRET,
			"is_active": 1,
			"maintenance_mode": 1 if maintenance else 0,
			"max_retries": 3,
			"retry_backoff_minutes": 30,
		}
	).insert()


def ensure_invoice(customer, total=120.0):
	return billing.issue_invoice(
		customer, [{"description": "Phase5 line", "qty": 1, "unit_price": total, "line_total": total}]
	)


def sign(raw):
	return hmac.new(SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()


def envelope(event_id, event_type, payment_ref, amount=120.0, currency="USD"):
	return json.dumps(
		{"id": event_id, "type": event_type, "payment_reference": payment_ref, "amount": amount, "currency": currency}
	)


class TestGatewayWebhooks(IntegrationTestCase):
	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.customer = ensure_user()
		self.gateway = ensure_gateway()

	def test_intent_uses_invoice_amount(self):
		invoice = ensure_invoice(self.customer, 120.0)
		payment = gateways.create_payment_intent(self.customer, invoice.name, self.gateway.name)
		self.assertEqual(float(payment.amount), 120.0)
		self.assertEqual(payment.status, "Created")
		self.assertEqual(payment.source_invoice, invoice.name)
		self.assertTrue(payment.gateway_reference)

	def test_intent_rejects_unsupported_currency(self):
		invoice = ensure_invoice(self.customer, 50.0)
		invoice.currency = "EUR"
		invoice.save()
		self.assertRaises(
			frappe.ValidationError, gateways.create_payment_intent, self.customer, invoice.name, self.gateway.name
		)

	def test_authorize_then_capture_allocates_invoice(self):
		invoice = ensure_invoice(self.customer, 120.0)
		payment = gateways.create_payment_intent(self.customer, invoice.name, self.gateway.name)
		raw = envelope("evt-p5-auth-1", "payment.authorized", payment.gateway_reference)
		webhooks.receive_webhook(self.gateway.name, raw, sign(raw))
		self.assertEqual(frappe.db.get_value("Hosting Payment Transaction", payment.name, "status"), "Authorized")
		raw = envelope("evt-p5-cap-1", "payment.captured", payment.gateway_reference)
		webhooks.receive_webhook(self.gateway.name, raw, sign(raw))
		payment.reload()
		self.assertEqual(payment.status, "Captured")
		invoice.reload()
		self.assertEqual(invoice.status, "Paid")

	def test_bad_signature_stores_failed_event(self):
		invoice = ensure_invoice(self.customer, 120.0)
		payment = gateways.create_payment_intent(self.customer, invoice.name, self.gateway.name)
		raw = envelope("evt-p5-bad-1", "payment.captured", payment.gateway_reference)
		self.assertRaises(frappe.PermissionError, webhooks.receive_webhook, self.gateway.name, raw, "wrong")
		event = frappe.get_doc("Hosting Payment Event", {"event_id": "evt-p5-bad-1"})
		self.assertEqual(event.status, "Failed")
		self.assertEqual(event.signature_valid, 0)
		self.assertEqual(frappe.db.get_value("Hosting Payment Transaction", payment.name, "status"), "Created")

	def test_bad_schema_throws(self):
		self.assertRaises(SchemaError, webhooks.validate_schema, {"no": "id"})
		self.assertRaises(
			SchemaError, webhooks.receive_webhook, self.gateway.name, "not json", sign("not json")
		)

	def test_duplicate_delivery_applies_once(self):
		invoice = ensure_invoice(self.customer, 120.0)
		payment = gateways.create_payment_intent(self.customer, invoice.name, self.gateway.name)
		raw = envelope("evt-p5-dup-1", "payment.captured", payment.gateway_reference)
		first = webhooks.receive_webhook(self.gateway.name, raw, sign(raw))
		second = webhooks.receive_webhook(self.gateway.name, raw, sign(raw))
		self.assertEqual(first.name, second.name)
		second.reload()
		self.assertEqual(second.status, "Processed")
		self.assertEqual(int(second.attempts), 2)
		allocations = frappe.get_all(
			"Hosting Payment Allocation", filters={"payment": payment.name}, pluck="name"
		)
		self.assertEqual(len(allocations), 1)

	def test_out_of_order_capture_walks_states(self):
		invoice = ensure_invoice(self.customer, 120.0)
		payment = gateways.create_payment_intent(self.customer, invoice.name, self.gateway.name)
		raw = envelope("evt-p5-ooo-1", "payment.captured", payment.gateway_reference)
		webhooks.receive_webhook(self.gateway.name, raw, sign(raw))
		self.assertEqual(frappe.db.get_value("Hosting Payment Transaction", payment.name, "status"), "Captured")

	def test_refund_and_chargeback_stay_separate(self):
		invoice = ensure_invoice(self.customer, 120.0)
		payment = gateways.create_payment_intent(self.customer, invoice.name, self.gateway.name)
		raw = envelope("evt-p5-cap-2", "payment.captured", payment.gateway_reference)
		webhooks.receive_webhook(self.gateway.name, raw, sign(raw))
		raw = envelope("evt-p5-ref-2", "refund.processed", payment.gateway_reference, amount=120.0)
		webhooks.receive_webhook(self.gateway.name, raw, sign(raw))
		payment.reload()
		self.assertEqual(payment.status, "Refunded")
		refunds = frappe.get_all("Hosting Refund", filters={"payment": payment.name}, fields=["status"])
		self.assertEqual(len(refunds), 1)
		invoice2 = ensure_invoice(self.customer, 60.0)
		payment2 = gateways.create_payment_intent(self.customer, invoice2.name, self.gateway.name)
		raw = envelope("evt-p5-cap-3", "payment.captured", payment2.gateway_reference, amount=60.0)
		webhooks.receive_webhook(self.gateway.name, raw, sign(raw))
		raw = envelope("evt-p5-cb-3", "charge.disputed", payment2.gateway_reference, amount=60.0)
		webhooks.receive_webhook(self.gateway.name, raw, sign(raw))
		payment2.reload()
		self.assertEqual(payment2.status, "Chargeback")
		row = frappe.get_all("Hosting Refund", filters={"payment": payment2.name}, fields=["status"])
		self.assertEqual(row[0].status, "Chargeback")

	def test_failed_payment_retry_and_terminal(self):
		invoice = ensure_invoice(self.customer, 120.0)
		payment = gateways.create_payment_intent(self.customer, invoice.name, self.gateway.name)
		raw = envelope("evt-p5-fail-1", "payment.failed", payment.gateway_reference)
		webhooks.receive_webhook(self.gateway.name, raw, sign(raw))
		payment.reload()
		self.assertEqual(payment.status, "Failed")
		invoice2 = ensure_invoice(self.customer, 30.0)
		retrying = gateways.create_payment_intent(self.customer, invoice2.name, self.gateway.name)
		gateways.schedule_retry(retrying.name, "gateway timeout")
		retrying.reload()
		self.assertEqual(retrying.status, "Failed")
		self.assertEqual(int(retrying.retry_count), 1)
		self.assertIsNotNone(retrying.next_retry_at)
		retrying.next_retry_at = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-1)
		retrying.save()
		gateways.retry_failed_payment(retrying.name)
		self.assertEqual(frappe.db.get_value("Hosting Payment Transaction", retrying.name, "status"), "Created")
		retrying.reload()
		retrying.retry_count = 3
		retrying.status = "Failed"
		retrying.next_retry_at = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-1)
		retrying.save()
		self.assertRaises(frappe.ValidationError, gateways.retry_failed_payment, retrying.name)

	def test_gateway_outage_marks_failed_with_retry(self):
		ensure_gateway(maintenance=True)
		invoice = ensure_invoice(self.customer, 40.0)
		self.assertRaises(
			GatewayOutage, gateways.create_payment_intent, self.customer, invoice.name, self.gateway.name
		)
		payment = frappe.get_all(
			"Hosting Payment Transaction", filters={"source_invoice": invoice.name}, fields=["status", "retry_count"]
		)
		self.assertEqual(len(payment), 1)
		self.assertEqual(payment[0].status, "Failed")
		self.assertEqual(int(payment[0].retry_count), 1)

	def test_method_stores_token_only(self):
		method = frappe.get_doc(
			{
				"doctype": "Hosting Payment Method",
				"customer": self.customer,
				"gateway": self.gateway.name,
				"token_reference": "tok_test_123",
				"brand": "Visa",
				"last4": "4242",
			}
		).insert()
		fields = {f.fieldname for f in frappe.get_meta("Hosting Payment Method").fields}
		self.assertTrue({"card_number", "pan", "cvv", "card_cvv"} & fields == set())
		invoice = ensure_invoice(self.customer, 25.0)
		payment = gateways.create_payment_intent(
			self.customer, invoice.name, self.gateway.name, payment_method=method.name
		)
		self.assertEqual(payment.payment_token_ref, "tok_test_123")

	def test_reconcile_finds_stuck_payment(self):
		invoice = ensure_invoice(self.customer, 77.0)
		payment = gateways.create_payment_intent(self.customer, invoice.name, self.gateway.name)
		report = gateways.reconcile_gateway(self.gateway.name)
		self.assertIn(payment.name, report["stuck_payments"])
		self.assertEqual(report["orphan_events"], [])

	def test_replay_failed_event(self):
		invoice = ensure_invoice(self.customer, 120.0)
		payment = gateways.create_payment_intent(self.customer, invoice.name, self.gateway.name)
		raw = envelope("evt-p5-replay-1", "payment.captured", "no-such-payment", amount=120.0)
		self.assertRaises(frappe.ValidationError, webhooks.receive_webhook, self.gateway.name, raw, sign(raw))
		event = frappe.get_doc("Hosting Payment Event", {"event_id": "evt-p5-replay-1"})
		self.assertEqual(event.status, "Failed")
		# Staff correct the reference, then replay applies the event.
		event.payload = envelope("evt-p5-replay-1", "payment.captured", payment.gateway_reference)
		event.save()
		webhooks.replay_payment_event(event.name)
		event.reload()
		self.assertEqual(event.status, "Processed")
		self.assertEqual(frappe.db.get_value("Hosting Payment Transaction", payment.name, "status"), "Captured")
		# Replaying a processed event is a no-op.
		webhooks.replay_payment_event(event.name)
		event.reload()
		self.assertEqual(event.status, "Processed")
