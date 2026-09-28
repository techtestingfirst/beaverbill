"""Phase 15 tests: health checks flag seeded faults, recon finds mismatches,
alerts dedup and resolve, dashboard stays staff-only."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_to_date, now_datetime, today

from beaverbill.beaverbill import billing, domains, monitoring, reconciliation
from beaverbill.beaverbill.domains import SimulatedRegistrarDriver


def wipe():
	for dt in [
		"Monitoring Alert",
		"Portal Audit Event",
		"Resource Cleanup Task",
		"Provisioning Attempt",
		"Provisioning Operation",
		"Hosting Subscription",
		"Hosting Payment Event",
		"Hosting Payment Allocation",
		"Hosting Payment Transaction",
		"Hosting Payment Gateway",
		"Hosting Invoice Item",
		"Hosting Invoice",
		"Customer Credit Transaction",
		"Service Backup",
		"Hosting DNS Record",
		"Hosting Domain",
		"IPAM IP Address",
		"IPAM Subnet",
		"Hosting Service",
		"Hosting Product",
		"Hosting Product Group",
		"Hosting Customer",
	]:
		try:
			names = frappe.get_all(dt, pluck="name")
		except Exception:
			continue
		for name in names:
			try:
				frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
			except Exception:
				try:
					frappe.db.delete(dt, name)
				except Exception:
					continue
	SimulatedRegistrarDriver.REGISTRY.clear()
	frappe.db.commit()


def ensure_user(email, first="Phase15"):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": first,
			"send_welcome_email": 0}).insert(ignore_permissions=True)
	try:
		frappe.get_doc("User", email).add_roles("Hosting Customer")
	except Exception:
		pass
	return email


def ensure_customer(user, name="P15 Buyer"):
	existing = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	if existing:
		return existing
	return frappe.get_doc({"doctype": "Hosting Customer", "customer_name": name,
		"primary_user": user, "status": "Active"}).insert().name


def ensure_gateway():
	if frappe.db.exists("Hosting Payment Gateway", "Phase15 Gateway"):
		return "Phase15 Gateway"
	return frappe.get_doc({"doctype": "Hosting Payment Gateway",
		"gateway_name": "Phase15 Gateway", "provider": "Test Gateway",
		"supported_currencies": "USD", "default_currency": "USD",
		"webhook_secret": "phase15-secret", "is_active": 1,
		"max_retries": 3, "retry_backoff_minutes": 30}).insert().name


class TestHealthChecks(IntegrationTestCase):
	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.user = ensure_user("phase15-buyer@example.com")
		ensure_customer(self.user)

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_checks_are_well_formed(self):
		results = monitoring.run_checks()
		self.assertEqual(len(results), len(monitoring.CHECKS))
		for row in results:
			self.assertIn(row["status"], ("ok", "warn", "fail"))
			self.assertTrue(row["check"].startswith("mon:"))

	def test_failed_payment_and_stale_webhook(self):
		payment = frappe.get_doc({"doctype": "Hosting Payment Transaction",
			"customer": self.user, "gateway": ensure_gateway(), "amount": 10,
			"currency": "USD", "status": "Created",
			"payment_date": today()}).insert()
		frappe.db.set_value("Hosting Payment Transaction", payment.name, "status",
			"Failed", update_modified=False)
		self.assertEqual(monitoring.check_failed_payments()["status"], "warn")
		event = frappe.get_doc({"doctype": "Hosting Payment Event",
			"event_id": "evt-p15-stale", "gateway": ensure_gateway(),
			"event_type": "payment.captured", "status": "Received",
			"payload_hash": "x", "attempts": 0,
			"idempotency_key": "evt-p15-stale"}).insert()
		frappe.db.set_value("Hosting Payment Event", event.name, "modified",
			add_to_date(now_datetime(), hours=-1), update_modified=False)
		out = monitoring.check_unprocessed_webhooks()
		self.assertIn(out["status"], ("warn", "fail"))
		self.assertGreaterEqual(out["count"], 1)

	def test_stuck_and_failed_provisioning(self):
		op = frappe.get_doc({"doctype": "Provisioning Operation",
			"operation_type": "Create", "status": "Queued",
			"idempotency_key": "phase15-stuck-1"}).insert()
		frappe.db.set_value("Provisioning Operation", op.name, "modified",
			add_to_date(now_datetime(), hours=-3), update_modified=False)
		out = monitoring.check_provisioning()
		self.assertEqual(out["status"], "fail")

	def test_expiring_domain_and_certificate(self):
		dom = frappe.get_doc({"doctype": "Hosting Domain",
			"domain_name": "urgent15.example.com", "customer": ensure_customer(self.user),
			"status": "Active", "expiry_date": add_days(today(), 3)}).insert()
		self.assertEqual(monitoring.check_expiring_domains()["status"], "fail")
		cert = frappe.get_doc({"doctype": "SSL Certificate", "domain": dom.name,
			"customer": ensure_customer(self.user), "status": "Active",
			"expires_at": add_days(today(), 3)}).insert()
		self.assertEqual(monitoring.check_expiring_certificates()["status"], "fail")

	def test_empty_ip_pool_flags_critical(self):
		subnet = frappe.get_doc({"doctype": "IPAM Subnet",
			"subnet_name": "P15 pool", "cidr": "192.0.2.0/30"}).insert()
		rows = frappe.get_all("IPAM IP Address",
			filters={"subnet": subnet.name, "status": "Available"}, pluck="name")
		self.assertTrue(rows)
		for index, name in enumerate(rows):
			frappe.db.set_value("IPAM IP Address", name,
				{"status": "Allocated", "allocated_to_doctype": "Hosting Service",
					"allocated_to_name": f"gone-{index}"}, update_modified=False)
		out = monitoring.check_ip_exhaustion()
		self.assertEqual(out["status"], "fail")


class TestReconciliation(IntegrationTestCase):
	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.user = ensure_user("phase15-recon@example.com", "Recon15")
		ensure_customer(self.user, "P15 Recon")

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_paid_with_balance_and_ledger_tamper(self):
		inv = billing.issue_invoice(self.user, [{
			"description": "P15 line", "qty": 1, "unit_price": 10, "line_total": 10}])
		frappe.db.set_value("Hosting Invoice", inv.name,
			{"status": "Paid", "paid_amount": 4}, update_modified=False)
		out = reconciliation.recon_invoices_vs_payments()
		self.assertGreaterEqual(out["count"], 1)
		billing.post_ledger(self.user, 50, "Credit", "P15 funding")
		row = frappe.get_all("Customer Credit Transaction", pluck="name", limit=1)[0]
		frappe.db.set_value("Customer Credit Transaction", row, "balance_after", 999999,
			update_modified=False)
		led = reconciliation.recon_ledger_vs_balances()
		self.assertGreaterEqual(led["count"], 1)

	def test_dangling_ipam_and_missing_domain(self):
		subnet = frappe.get_doc({"doctype": "IPAM Subnet",
			"subnet_name": "P15 recon", "cidr": "198.51.100.0/30"}).insert()
		name = frappe.get_all("IPAM IP Address",
			filters={"subnet": subnet.name, "status": "Available"},
			pluck="name", limit=1)[0]
		frappe.db.set_value("IPAM IP Address", name,
			{"status": "Allocated", "allocated_to_doctype": "Hosting Service",
				"allocated_to_name": "no-such-service"}, update_modified=False)
		ipam = reconciliation.recon_ipam_vs_assignments()
		self.assertGreaterEqual(ipam["count"], 1)
		reg = domains.register_domain(ensure_customer(self.user), "gone15.example.com")
		del SimulatedRegistrarDriver.REGISTRY["gone15.example.com"]
		missing = reconciliation.recon_domains_vs_registrar()
		self.assertGreaterEqual(missing["count"], 1)

	def test_cycle_raises_and_resolves(self):
		inv = billing.issue_invoice(self.user, [{
			"description": "P15 line", "qty": 1, "unit_price": 10, "line_total": 10}])
		frappe.db.set_value("Hosting Invoice", inv.name,
			{"status": "Paid", "paid_amount": 1}, update_modified=False)
		first = reconciliation.run_reconciliation_cycle()
		self.assertIn("recon:invoices_vs_payments", first["failing"])
		open_alerts = frappe.get_all("Monitoring Alert",
			filters={"status": "Open", "check": "recon:invoices_vs_payments"})
		self.assertEqual(len(open_alerts), 1)
		second = reconciliation.run_reconciliation_cycle()
		self.assertIn("recon:invoices_vs_payments", second["failing"])
		self.assertEqual(len(frappe.get_all("Monitoring Alert",
			filters={"status": "Open", "check": "recon:invoices_vs_payments"})), 1)
		frappe.db.set_value("Hosting Invoice", inv.name, "paid_amount", 10,
			update_modified=False)
		third = reconciliation.run_reconciliation_cycle()
		self.assertNotIn("recon:invoices_vs_payments", third["failing"])
		self.assertEqual(len(frappe.get_all("Monitoring Alert",
			filters={"status": "Open", "check": "recon:invoices_vs_payments"})), 0)


class TestDashboardAccess(IntegrationTestCase):
	def test_customer_denied_admin_allowed(self):
		frappe.set_user("Administrator")
		user = ensure_user("phase15-dash@example.com", "Dash15")
		ensure_customer(user, "P15 Dash")
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			monitoring.health_dashboard()
		frappe.set_user("Administrator")
		out = monitoring.health_dashboard()
		self.assertIn("checks", out)
		self.assertIn("open_alerts", out)
		frappe.set_user("Administrator")
