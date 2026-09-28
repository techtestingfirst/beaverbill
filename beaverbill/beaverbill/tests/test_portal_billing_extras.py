"""Phase 11 tests: gateway listing and tokenized payment-method management."""

import frappe
from frappe.tests import IntegrationTestCase

from beaverbill.beaverbill.portal import billing


def wipe():
	for dt in ["Hosting Payment Method", "Hosting Payment Gateway", "Hosting Customer"]:
		for name in frappe.get_all(dt, pluck="name"):
			frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
	frappe.db.commit()


def ensure_user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "P11", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	user = frappe.get_doc("User", email)
	user.add_roles("Hosting Customer")
	return email


def ensure_customer(user):
	name = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	if name:
		return name
	return frappe.get_doc(
		{"doctype": "Hosting Customer", "customer_name": "P11", "primary_user": user, "status": "Active"}
	).insert().name


class TestPortalBillingExtras(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.user_a = ensure_user("phase11a@example.com")
		self.user_b = ensure_user("phase11b@example.com")
		ensure_customer(self.user_a)
		ensure_customer(self.user_b)
		self.gateway = frappe.get_doc(
			{"doctype": "Hosting Payment Gateway", "gateway_name": "P11 GW",
			 "provider": "Test Gateway", "supported_currencies": "USD,INR",
			 "default_currency": "USD", "is_active": 1}
		).insert().name
		frappe.set_user(self.user_a)

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_list_gateways_filters_currency(self):
		all_gw = billing.list_gateways.__wrapped__()
		self.assertTrue([g for g in all_gw["gateways"] if g["name"] == self.gateway])
		usd = billing.list_gateways.__wrapped__(currency="USD")
		self.assertTrue([g for g in usd["gateways"] if g["name"] == self.gateway])
		eur = billing.list_gateways.__wrapped__(currency="EUR")
		self.assertFalse([g for g in eur["gateways"] if g["name"] == self.gateway])

	def test_add_list_remove_method(self):
		added = billing.add_payment_method.__wrapped__(
			self.gateway, "tok_test_123", brand="Visa", last4="1234",
			exp_month="12", exp_year="2030", make_default=True)
		rows = billing.list_payment_methods.__wrapped__()
		self.assertTrue([m for m in rows["methods"] if m["name"] == added["method"]])
		self.assertNotIn("tok_test_123", str(rows))
		second = billing.add_payment_method.__wrapped__(self.gateway, "tok_test_456")
		rows = billing.list_payment_methods.__wrapped__()
		defaults = [m for m in rows["methods"] if m["is_default"]]
		self.assertEqual(len(defaults), 1)
		_ = second
		out = billing.remove_payment_method.__wrapped__(added["method"])
		self.assertEqual(out["deleted"], added["method"])

	def test_raw_card_data_refused(self):
		with self.assertRaises(frappe.ValidationError):
			billing.add_payment_method.__wrapped__(self.gateway, "tok", last4="4111111111111111")
		with self.assertRaises(frappe.ValidationError):
			billing.add_payment_method.__wrapped__(self.gateway, token_reference="")
		with self.assertRaises(frappe.ValidationError):
			billing.add_payment_method.__wrapped__(self.gateway, "tok_ok_1", last4="12")

	def test_cross_customer_method_denied(self):
		added = billing.add_payment_method.__wrapped__(self.gateway, "tok_mine_1")
		frappe.set_user(self.user_b)
		self.assertEqual(billing.list_payment_methods.__wrapped__()["methods"], [])
		with self.assertRaises(frappe.PermissionError):
			billing.remove_payment_method.__wrapped__(added["method"])
