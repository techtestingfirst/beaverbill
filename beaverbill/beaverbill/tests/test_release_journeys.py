"""Phase 14 billing-to-termination lifecycle (portal, gateway, provision,
modify, renew, dun, cancel). Companion: test_release_journeys_assets.py.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from beaverbill.beaverbill import (
	billing,
	gateways,
	modifications,
	provisioning,
	subscription_lifecycle,
	subscriptions,
	webhooks,
)
from beaverbill.beaverbill.portal import billing as portal_billing
from beaverbill.beaverbill.portal import orders, services
from beaverbill.beaverbill.tests.release_helpers import (
	ensure_customer,
	ensure_gateway,
	ensure_products,
	ensure_provider_account,
	ensure_user,
	envelope,
	sign,
	wipe,
)


def make_subscription(user, product, **over):
	doc = {"doctype": "Hosting Subscription", "customer": user, "product": product,
		"status": "Active", "billing_cycle": "Monthly", "amount": 10,
		"currency": "USD", "next_renewal_date": today(),
		"current_period_start": add_days(today(), -30),
		"current_period_end": today(), "renewal_lead_days": 3,
		"grace_period_days": 7, "max_retries": 2, "retry_backoff_minutes": 60}
	doc.update(over)
	return frappe.get_doc(doc).insert()


class TestCheckoutToCash(IntegrationTestCase):
	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.user = ensure_user("phase14-buyer@example.com")
		self.customer = ensure_customer(self.user)
		self.small, self.large = ensure_products()
		self.gateway = ensure_gateway()

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_cart_checkout_payment_invoice_paid(self):
		frappe.set_user(self.user)
		with self.assertRaises(frappe.ValidationError):
			orders.cart_coupon.__wrapped__("NOPE")
		orders.cart_add.__wrapped__(self.small)
		out = orders.checkout.__wrapped__("phase14-checkout-1")
		self.assertFalse(out.get("duplicate_request"))
		dup = orders.checkout.__wrapped__("phase14-checkout-1")
		self.assertTrue(dup.get("duplicate_request"))
		order = frappe.get_doc("Hosting Order", out["order"])
		self.assertEqual(order.status, "Payment Pending")
		invoice = frappe.get_all("Hosting Invoice",
			filters={"order": out["order"]}, pluck="name")
		if not invoice:
			invoice = frappe.get_all("Hosting Invoice", pluck="name",
				filters={"customer": self.user}, limit=1)
		inv = frappe.get_doc("Hosting Invoice", invoice[0])
		payment = gateways.create_payment_intent(self.user, inv.name, self.gateway)
		frappe.set_user("Administrator")
		webhooks.receive_webhook(self.gateway,
			envelope("evt-p14-auth", "payment.authorized", payment.gateway_reference),
			sign(envelope("evt-p14-auth", "payment.authorized", payment.gateway_reference)))
		raw = envelope("evt-p14-cap", "payment.captured", payment.gateway_reference)
		webhooks.receive_webhook(self.gateway, raw, sign(raw))
		inv.reload()
		self.assertEqual(inv.status, "Paid")
		frappe.set_user(self.user)
		seen = portal_billing.get_invoice.__wrapped__(inv.name)
		self.assertEqual(seen["status"], "Paid")


class TestProvisionAndOperate(IntegrationTestCase):
	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.user = ensure_user("phase14-ops@example.com", "Ops14")
		self.customer = ensure_customer(self.user, "P14 Ops")
		self.small, self.large = ensure_products()
		self.account = ensure_provider_account()
		sub = make_subscription(self.user, self.small)
		self.sub = sub.name
		self.service = frappe.get_doc({"doctype": "Hosting Service",
			"customer": self.customer, "status": "Pending", "product": self.small,
			"billing_cycle": "Monthly", "subscription": self.sub,
			"provider_account": self.account}).insert().name

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_create_run_power_console(self):
		frappe.set_user("Administrator")
		op = provisioning.queue_operation(service=self.service,
			operation_type="Create", idempotency_key="phase14-create-1")
		done = provisioning.run_operation(op.name)
		self.assertEqual(done.status, "Succeeded")
		self.assertEqual(frappe.db.get_value("Hosting Service", self.service, "status"),
			"Active")
		frappe.set_user(self.user)
		powered = services.power.__wrapped__(self.service, "reboot")
		self.assertEqual(powered["action"], "reboot")
		ticket = services.console_url.__wrapped__(self.service)
		self.assertTrue(ticket["ticket"])
		first = services.console_ticket.__wrapped__(ticket["ticket"])
		self.assertEqual(first["service"], self.service)
		with self.assertRaises(frappe.PermissionError):
			services.console_ticket.__wrapped__(ticket["ticket"])

	def test_upgrade_renew_dunning_reinstate_cancel_terminate(self):
		frappe.set_user("Administrator")
		created = provisioning.run_operation(provisioning.queue_operation(
			service=self.service, operation_type="Create",
			idempotency_key="phase14-create-2").name)
		self.assertEqual(created.status, "Succeeded")
		billing.post_ledger(self.user, 500, "Credit", "Phase14 funding")
		req = modifications.request_modification(self.sub, self.large)
		modifications.approve_modification(req.name)
		self.assertIsNotNone(frappe.db.get_value(
			"Hosting Service Modification Request", req.name, "invoice"))
		out = subscriptions.process_subscription_renewals()
		self.assertIn(self.sub, out["renewed"])
		poor_user = ensure_user("phase14-poor@example.com", "Poor14")
		ensure_customer(poor_user, "P14 Poor")
		poor = make_subscription(poor_user, self.small, max_retries=1)
		poor_out = subscriptions.process_subscription_renewals()
		self.assertIn(poor.name, poor_out["payment-failed"])
		poor.reload()
		self.assertEqual(poor.status, "Grace Period")
		subscription_lifecycle.reinstate_subscription(poor.name)
		self.assertEqual(frappe.db.get_value(
			"Hosting Subscription", poor.name, "status"), "Active")
		subscription_lifecycle.cancel_subscription(self.sub, mode="end_of_period")
		self.assertEqual(frappe.db.get_value(
			"Hosting Subscription", self.sub, "status"), "Cancellation Pending")
		op = provisioning.queue_operation(service=self.service,
			operation_type="Terminate", idempotency_key="phase14-term-1")
		svc = frappe.get_doc("Hosting Service", self.service)
		svc.status = "Cancellation Pending"
		svc.save()
		done = provisioning.run_operation(op.name)
		self.assertEqual(done.status, "Succeeded")
		self.assertEqual(frappe.db.get_value("Hosting Service", self.service, "status"),
			"Terminated")


class TestMoneyEdgeCases(IntegrationTestCase):
	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.user = ensure_user("phase14-money@example.com", "Money14")
		ensure_customer(self.user, "P14 Money")
		self.gateway = ensure_gateway()
		inv = billing.issue_invoice(self.user, [{
			"description": "P14 line", "qty": 1, "unit_price": 10, "line_total": 10}])
		self.invoice = inv.name
		self.payment = gateways.create_payment_intent(
			self.user, self.invoice, self.gateway).name

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_duplicate_webhook_single_transition(self):
		raw = envelope("evt-p14-dup", "payment.captured",
			frappe.db.get_value("Hosting Payment Transaction",
				self.payment, "gateway_reference"))
		first = webhooks.receive_webhook(self.gateway, raw, sign(raw))
		second = webhooks.receive_webhook(self.gateway, raw, sign(raw))
		self.assertEqual(first.name, second.name)
		self.assertEqual(frappe.db.get_value(
			"Hosting Payment Transaction", self.payment, "status"), "Captured")

	def test_failure_then_staff_retry(self):
		ref = frappe.db.get_value("Hosting Payment Transaction",
			self.payment, "gateway_reference")
		raw = envelope("evt-p14-fail", "payment.failed", ref)
		event = webhooks.receive_webhook(self.gateway, raw, sign(raw))
		self.assertEqual(event.status, "Processed")
		self.assertEqual(frappe.db.get_value(
			"Hosting Payment Transaction", self.payment, "status"), "Failed")
		frappe.set_user("Administrator")
		gateways.retry_failed_payment(self.payment)
		self.assertEqual(frappe.db.get_value(
			"Hosting Payment Transaction", self.payment, "status"), "Created")
