"""Phase 17 tests: business policies match enforced code, guides exist.

Each test ties a documented policy number to the constant, transition,
default, or flow that enforces it, so policy drift fails the suite.
Documentation structure (required guides and sections) is checked too.
"""

import os

import frappe
from frappe.tests import IntegrationTestCase

from beaverbill.beaverbill import subscriptions
from beaverbill.beaverbill import domains as domains_mod

APP_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
DOCS = os.path.join(APP_ROOT, "..", "docs")


def read_doc(name):
	with open(os.path.join(DOCS, name), encoding="utf-8") as handle:
		return handle.read()


class TestPolicyEnforcement(IntegrationTestCase):
	def test_termination_purge_window(self):
		self.assertEqual(subscriptions.PURGE_AFTER_TERMINATE_DAYS, 30)

	def test_domain_renewal_terms(self):
		self.assertEqual(domains_mod.RENEWAL_PRICE, 15.0)
		self.assertEqual(domains_mod.RENEWAL_CURRENCY, "USD")
		self.assertEqual(domains_mod.AUTO_RENEW_WITHIN_DAYS, 7)
		self.assertEqual(domains_mod.GRACE_DAYS, 30)

	def test_certificate_lifetime(self):
		from beaverbill.beaverbill import certificates

		self.assertEqual(certificates.CERT_VALIDITY_DAYS, 90)

	def test_dunning_defaults(self):
		import json

		with open(os.path.join(APP_ROOT, "beaverbill", "doctype",
				"hosting_subscription", "hosting_subscription.json"),
				encoding="utf-8") as handle:
			doc = json.load(handle)
		defaults = {f["fieldname"]: f.get("default") for f in doc["fields"]}
		self.assertEqual(defaults["renewal_lead_days"], "3")
		self.assertEqual(defaults["grace_period_days"], "7")
		self.assertEqual(defaults["max_retries"], "4")

	def test_backup_policy_defaults(self):
		import json

		with open(os.path.join(APP_ROOT, "beaverbill", "doctype",
				"backup_policy", "backup_policy.json"), encoding="utf-8") as handle:
			doc = json.load(handle)
		defaults = {f["fieldname"]: f.get("default") for f in doc["fields"]}
		self.assertEqual(defaults["frequency"], "Daily")
		self.assertEqual(defaults["retention_count"], 7)
		self.assertEqual(defaults["retention_days"], 30)

	def test_cancel_modes_and_reinstate_states(self):
		from beaverbill.beaverbill import subscription_lifecycle as lifecycle
		from frappe.utils import add_days, today

		frappe.set_user("Administrator")
		customer = "phase17-cancel@example.com"
		if not frappe.db.exists("User", customer):
			frappe.get_doc({"doctype": "User", "email": customer,
				"first_name": "P17", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Hosting Product Group", "Phase17 Group"):
			frappe.get_doc({"doctype": "Hosting Product Group",
				"product_group_name": "Phase17 Group"}).insert()
		if not frappe.db.exists("Hosting Product", "Phase17 VPS"):
			frappe.get_doc({"doctype": "Hosting Product", "product_name": "Phase17 VPS",
				"product_group": "Phase17 Group", "billing_cycle": "Monthly",
				"price": 100, "currency": "USD"}).insert()
		sub = frappe.get_doc({"doctype": "Hosting Subscription",
			"customer": customer, "product": "Phase17 VPS",
			"status": "Active", "billing_cycle": "Monthly", "amount": 100,
			"currency": "USD", "next_renewal_date": today(),
			"current_period_start": add_days(today(), -30),
			"current_period_end": today()}).insert()
		lifecycle.cancel_subscription(sub.name, mode="end_of_period")
		self.assertEqual(frappe.db.get_value(
			"Hosting Subscription", sub.name, "status"), "Cancellation Pending")
		lifecycle.reinstate_subscription(sub.name)
		self.assertEqual(frappe.db.get_value(
			"Hosting Subscription", sub.name, "status"), "Active")
		frappe.delete_doc("Hosting Subscription", sub.name,
			ignore_permissions=True, force=True)
		frappe.db.commit()

	def test_refund_posts_ledger_credit(self):
		from beaverbill.beaverbill import billing

		frappe.set_user("Administrator")
		user = "phase17-refund@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user,
				"first_name": "P17", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		refund = billing.process_refund(user, 25,
			reason="policy test", idempotency_key="phase17-pol-refund")
		balance = billing.get_ledger_balance(user)
		self.assertEqual(float(balance), 25.0)
		frappe.delete_doc("Hosting Refund", refund.name,
			ignore_permissions=True, force=True)
		frappe.db.delete("Customer Credit Transaction",
			{"customer": user})
		frappe.db.commit()
		frappe.set_user("Administrator")


class TestDocumentationReview(IntegrationTestCase):
	def test_policy_sections_present(self):
		text = read_doc("policies.md")
		for section in ("Terms of Service", "Acceptable Use", "Privacy",
				"Refund", "Cancellation", "Upgrade", "Suspension",
				"Termination", "Backup", "Domain", "SSL", "Overage",
				"Maintenance", "SLA", "Chargeback", "Wallet"):
			self.assertIn(section, text)

	def test_guides_present(self):
		text = read_doc("guides.md")
		for section in ("Customer Guide", "Administrator Guide",
				"Provider Setup", "API Reference", "Troubleshooting",
				"Runbooks"):
			self.assertIn(section, text)

	def test_architecture_present(self):
		text = read_doc("architecture.md")
		for section in ("Module map", "State machines", "Money flow",
				"Why no ERPNext"):
			self.assertIn(section, text)
