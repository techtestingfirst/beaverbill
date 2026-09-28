"""Phase 14 release health: schema, migration, dependency, and perf smoke.

Fast static checks that run without fixtures (except one priced product
for the perf smoke). They guard the release gates that unit tests miss:
patches registered, DocType JSON valid, state machines complete,
no ERPNext dependency, scheduler wired, and pricing not regressed.
"""

import json
import os
import time

import frappe
from frappe.tests import IntegrationTestCase

from beaverbill import hooks
from beaverbill.beaverbill import pricing

APP_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def doctype_dirs():
	base = os.path.join(APP_ROOT, "beaverbill", "doctype")
	return [os.path.join(base, name) for name in sorted(os.listdir(base))
		if os.path.isdir(os.path.join(base, name))]


def status_options(doctype):
	path = os.path.join(APP_ROOT, "beaverbill", "doctype",
		doctype, f"{doctype}.json")
	with open(path, encoding="utf-8") as handle:
		doc = json.load(handle)
	for field in doc.get("fields", []):
		if field.get("fieldname") == "status":
			return set(filter(None, str(field.get("options", "")).split("\n")))
	return set()


class TestReleaseHealth(IntegrationTestCase):
	def test_patches_registered_and_present(self):
		with open(os.path.join(APP_ROOT, "patches.txt"), encoding="utf-8") as handle:
			entries = [line.strip() for line in handle
				if line.strip().startswith("beaverbill.patches.")]
		self.assertTrue(entries)
		for entry in entries:
			relative = os.path.join(*entry.split(".")[1:]) + ".py"
			self.assertTrue(os.path.isfile(os.path.join(APP_ROOT, relative)), entry)

	def test_doctype_json_valid_and_permissioned(self):
		checked = 0
		for directory in doctype_dirs():
			name = os.path.basename(directory)
			path = os.path.join(directory, f"{name}.json")
			if not os.path.isfile(path):
				continue
			with open(path, encoding="utf-8") as handle:
				doc = json.load(handle)
			if not doc.get("istable"):
				self.assertTrue(doc.get("permissions"), name)
			self.assertEqual(doc.get("module"), "BeaverBill", name)
			checked += 1
		self.assertGreater(checked, 40)

	def test_state_machines_cover_plan(self):
		self.assertTrue({"Draft", "Issued", "Partially Paid", "Paid", "Overdue",
			"Cancelled", "Written Off"} <= status_options("hosting_invoice"))
		self.assertTrue({"Trial", "Active", "Renewal Pending", "Payment Failed",
			"Grace Period", "Suspended", "Cancellation Pending", "Terminated",
			"Archived"} <= status_options("hosting_subscription"))
		self.assertTrue({"Pending", "Provisioning", "Active", "Modification Pending",
			"Suspended", "Cancellation Pending", "Terminated", "Archived"}
			<= status_options("hosting_service"))
		self.assertTrue({"Draft", "Confirmed", "Payment Pending", "Paid", "Processing",
			"Completed", "Cancelled"} <= status_options("hosting_order"))
		self.assertTrue({"Created", "Authorized", "Captured", "Failed", "Refunded",
			"Partially Refunded", "Chargeback"}
			<= status_options("hosting_payment_transaction"))

	def test_no_erpnext_dependency(self):
		self.assertEqual(list(getattr(hooks, "required_apps", [])), ["frappe"])
		for dirpath, dirnames, filenames in os.walk(os.path.join(APP_ROOT, "beaverbill")):
			dirnames[:] = [d for d in dirnames if d != "__pycache__"]
			for filename in filenames:
				if not filename.endswith(".py"):
					continue
				with open(os.path.join(dirpath, filename), encoding="utf-8") as handle:
					for line in handle:
						stripped = line.strip()
						if stripped.startswith("import erpnext") \
								or stripped.startswith("from erpnext"):
							self.fail(f"{filename}: {stripped}")

	def test_scheduler_covers_lifecycle(self):
		daily = hooks.scheduler_events.get("daily", [])
		for job in (
			"process_subscription_renewals",
			"process_queued_provisioning_operations",
			"process_domain_renewals",
			"monitor_certificates",
			"run_due_backups",
			"process_helpdesk_sync",
		):
			self.assertTrue(any(job in entry for entry in daily), job)

	def test_portal_route_registered(self):
		rules = getattr(hooks, "website_route_rules", [])
		self.assertTrue(any("/beaverbill" in str(rule) for rule in rules))

	def test_pricing_perf_smoke(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Hosting Product Group", "Phase14 Group"):
			frappe.get_doc({"doctype": "Hosting Product Group",
				"product_group_name": "Phase14 Group"}).insert()
		if not frappe.db.exists("Hosting Product", "Phase14 Small"):
			frappe.get_doc({"doctype": "Hosting Product", "product_name": "Phase14 Small",
				"product_group": "Phase14 Group", "billing_cycle": "Monthly",
				"price": 10, "currency": "USD"}).insert()
		started = time.monotonic()
		for _ in range(100):
			quote = pricing.calculate_price("Phase14 Small")
			self.assertEqual(float(quote["total_price"]), 10.0)
		self.assertLess(time.monotonic() - started, 30)
