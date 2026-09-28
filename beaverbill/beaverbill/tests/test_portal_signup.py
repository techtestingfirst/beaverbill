"""Phase 11 tests: public signup and email verification."""

import frappe
from frappe.tests import IntegrationTestCase

from beaverbill.beaverbill.portal import public


def wipe():
	for dt in ["Hosting Customer", "Portal Audit Event", "Customer Notification"]:
		for name in frappe.get_all(dt, pluck="name"):
			frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
	for mail in ("phase11new@example.com", "phase11dup@example.com"):
		if frappe.db.exists("User", mail):
			frappe.delete_doc("User", mail, ignore_permissions=True, force=True)
	frappe.db.commit()


class TestPortalSignup(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		frappe.set_user("Guest")

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_signup_creates_user_and_customer(self):
		out = public.signup.__wrapped__("New Buyer", "s3cure-pass", "phase11new@example.com")
		self.assertEqual(out["user"], "phase11new@example.com")
		roles = [r.role for r in frappe.get_doc("User", out["user"]).roles]
		self.assertIn("Hosting Customer", roles)
		customer = frappe.db.get_value("Hosting Customer", {"primary_user": out["user"]}, "name")
		self.assertEqual(customer, out["customer"])
		self.assertEqual(int(frappe.db.get_value("Hosting Customer", customer, "email_verified")), 0)

	def test_signup_duplicate_refused(self):
		public.signup.__wrapped__("Dup Buyer", "s3cure-pass", "phase11dup@example.com")
		with self.assertRaises(frappe.ValidationError):
			public.signup.__wrapped__("Dup Buyer", "s3cure-pass", "phase11dup@example.com")

	def test_signup_validation(self):
		with self.assertRaises(frappe.ValidationError):
			public.signup.__wrapped__("X", "s3cure-pass", "not-an-email")
		with self.assertRaises(frappe.ValidationError):
			public.signup.__wrapped__("New Buyer", "short", "phase11ok@example.com")
		with self.assertRaises(frappe.ValidationError):
			public.signup.__wrapped__("", "s3cure-pass", "phase11ok@example.com")

	def test_verify_flow(self):
		public.signup.__wrapped__("New Buyer", "s3cure-pass", "phase11new@example.com")
		token = frappe.cache().get_value(public._pending_key("phase11new@example.com"))
		self.assertTrue(token)
		out = public.verify_email.__wrapped__(token)
		self.assertTrue(out["verified"])
		customer = frappe.db.get_value("Hosting Customer", {"primary_user": out["user"]}, "name")
		self.assertEqual(int(frappe.db.get_value("Hosting Customer", customer, "email_verified")), 1)
		with self.assertRaises(frappe.ValidationError):
			public.verify_email.__wrapped__(token)

	def test_verify_bad_token(self):
		with self.assertRaises(frappe.ValidationError):
			public.verify_email.__wrapped__("nope-not-a-token")

	def test_resend_never_enumerates(self):
		out = public.resend_verification.__wrapped__("ghost@example.com")
		self.assertTrue(out["sent"])
		public.signup.__wrapped__("New Buyer", "s3cure-pass", "phase11new@example.com")
		again = public.resend_verification.__wrapped__("phase11new@example.com")
		self.assertTrue(again["sent"])
