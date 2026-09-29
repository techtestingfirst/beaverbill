"""Settings tests: BeaverBill Settings Single resolves legacy defaults,
overrides take effect in engines, and module constants stay compatible.
"""

import frappe
from frappe.tests import IntegrationTestCase

from beaverbill.beaverbill import settings as bb_settings


class TestBeaverBillSettings(IntegrationTestCase):
	def test_defaults_match_legacy(self):
		values = bb_settings.get_all()
		self.assertEqual(values["terminate_after_suspend_days"], 14)
		self.assertEqual(values["purge_after_terminate_days"], 30)
		self.assertEqual(values["domain_renewal_price"], 15.0)
		self.assertEqual(values["domain_renewal_currency"], "USD")
		self.assertEqual(values["cert_validity_days"], 90)
		self.assertEqual(values["session_ttl_hours"], 12)
		self.assertEqual(values["console_ttl_minutes"], 15)
		self.assertEqual(values["sync_max_attempts"], 5)

	def test_reminder_stages_parse(self):
		self.assertEqual(bb_settings.get_reminder_stages(), (30, 14, 7, 1))

	def test_override_takes_effect(self):
		doc = frappe.get_single("BeaverBill Settings")
		previous = doc.get("terminate_after_suspend_days")
		try:
			doc.db_set("terminate_after_suspend_days", 21)
			frappe.db.commit()
			self.assertEqual(bb_settings.get_int("terminate_after_suspend_days"), 21)
		finally:
			doc.db_set("terminate_after_suspend_days", previous or 0)
			frappe.db.commit()
		# 0/unset falls back to the legacy default.
		self.assertEqual(bb_settings.get_int("terminate_after_suspend_days"), 14)

	def test_engines_use_settings(self):
		from beaverbill.beaverbill import subscriptions

		doc = frappe.get_single("BeaverBill Settings")
		previous = doc.get("purge_after_terminate_days")
		try:
			doc.db_set("purge_after_terminate_days", 45)
			frappe.db.commit()
			self.assertEqual(subscriptions._purge_after_terminate_days(), 45)
		finally:
			doc.db_set("purge_after_terminate_days", previous or 0)
			frappe.db.commit()
