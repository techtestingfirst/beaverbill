"""Phase 9 tests: domains, DNS, SSL, backups, storage overage, addons."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from beaverbill.beaverbill import addons, backups, certificates, domains
from beaverbill.beaverbill.domains import SimulatedRegistrarDriver


def wipe():
	for dt in [
		"Restore Request",
		"Service Backup",
		"Backup Policy",
		"Service Addon",
		"Service Storage Usage",
		"SSL Certificate",
		"Hosting DNS Record",
		"Hosting Domain",
		"Domain Registrar Account",
		"Hosting Payment Allocation",
		"Hosting Payment Transaction",
		"Hosting Invoice Item",
		"Hosting Invoice",
		"Resource Cleanup Task",
		"Hosting Service",
		"Hosting Subscription",
		"Hosting Product Addon",
		"Hosting Product",
		"Hosting Customer",
	]:
		for name in frappe.get_all(dt, pluck="name"):
			frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
	SimulatedRegistrarDriver.REGISTRY.clear()
	domains.REGISTRAR_FAULTS.clear()
	certificates.CERT_FAULTS.clear()
	backups.BACKUP_FAULTS.clear()
	addons.ADDON_FAULTS.clear()
	frappe.db.commit()


def ensure_user(email="phase9-buyer@example.com"):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Phase9", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return email


def ensure_customer(user):
	name = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	if name:
		return name
	return frappe.get_doc(
		{"doctype": "Hosting Customer", "customer_name": "Phase9 Buyer",
		 "primary_user": user, "status": "Active"}
	).insert().name


def ensure_product(name="Phase9 Small"):
	if not frappe.db.exists("Hosting Product Group", "Phase9 Group"):
		frappe.get_doc({"doctype": "Hosting Product Group", "product_group_name": "Phase9 Group"}).insert()
	if frappe.db.exists("Hosting Product", name):
		return name
	return frappe.get_doc(
		{
			"doctype": "Hosting Product",
			"product_name": name,
			"product_group": "Phase9 Group",
			"billing_cycle": "Monthly",
			"price": 10,
			"currency": "USD",
		}
	).insert().name


def ensure_addon_row(product, name="Phase9 Extra Disk", price=5):
	if frappe.db.exists("Hosting Product Addon", {"addon_name": name}):
		return frappe.db.get_value("Hosting Product Addon", {"addon_name": name}, "name")
	return frappe.get_doc(
		{"doctype": "Hosting Product Addon", "addon_name": name, "product": product, "price": price}
	).insert().name


def make_service(customer, product):
	return frappe.get_doc(
		{
			"doctype": "Hosting Service",
			"customer": customer,
			"status": "Pending",
			"product": product,
			"billing_cycle": "Monthly",
		}
	).insert()


def mark_paid(invoice_name):
	inv = frappe.get_doc("Hosting Invoice", invoice_name)
	inv.paid_amount = inv.total_amount
	inv.outstanding_amount = 0
	inv.status = "Paid"
	inv.save()
	return inv


class TestDomains(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.customer = ensure_customer(ensure_user())
		self.product = ensure_product()
		self.service = make_service(self.customer, self.product)

	def tearDown(self):
		wipe()

	def test_register_success(self):
		out = domains.register_domain(self.customer, "Example-Success.com", service=self.service.name)
		self.assertEqual(out["status"], "Active")
		doc = frappe.get_doc("Hosting Domain", out["domain"])
		self.assertEqual(doc.domain_name, "example-success.com")
		self.assertIsNotNone(doc.expiry_date)
		self.assertTrue(doc.nameservers)

	def test_register_idempotent(self):
		first = domains.register_domain(self.customer, "example-idem.com", idempotency_key="k1")
		second = domains.register_domain(self.customer, "other.com", idempotency_key="k1")
		self.assertEqual(first["domain"], second["domain"])
		self.assertTrue(second.get("duplicate_request"))

	def test_register_duplicate_name_refused(self):
		domains.register_domain(self.customer, "example-dup.com")
		with self.assertRaises(frappe.ValidationError):
			domains.register_domain(self.customer, "example-dup.com", idempotency_key="k2")

	def test_register_invalid_name_refused(self):
		with self.assertRaises(frappe.ValidationError):
			domains.register_domain(self.customer, "not a domain!!")

	def test_registrar_failure_then_retry(self):
		domains.REGISTRAR_FAULTS["register"] = "upstream timeout"
		out = domains.register_domain(self.customer, "example-flaky.com")
		self.assertEqual(out["status"], "Cancelled")
		self.assertIn("upstream timeout", frappe.db.get_value("Hosting Domain", out["domain"], "failure_reason"))
		domains.REGISTRAR_FAULTS.clear()
		retried = domains.retry_domain_registration(out["domain"])
		self.assertEqual(retried["status"], "Active")

	def test_renewal_invoice_then_paid_renew(self):
		out = domains.register_domain(self.customer, "example-renew.com")
		first = domains.renew_domain(out["domain"])
		self.assertFalse(first["renewed"])
		inv = first["invoice"]
		again = domains.renew_domain(out["domain"])
		self.assertEqual(again["invoice"], inv, "renewal invoice must be idempotent while unpaid")
		before = frappe.db.get_value("Hosting Domain", out["domain"], "expiry_date")
		mark_paid(inv)
		done = domains.renew_domain(out["domain"])
		self.assertTrue(done["renewed"])
		after = frappe.db.get_value("Hosting Domain", out["domain"], "expiry_date")
		self.assertGreater(str(after), str(before))

	def test_transfer_round_trip(self):
		out = domains.register_domain(self.customer, "example-transfer.com")
		moved = domains.transfer_domain(out["domain"], "auth-123")
		self.assertEqual(moved["status"], "Active")
		self.assertEqual(frappe.db.get_value("Hosting Domain", out["domain"], "transfer_status"), "Completed")

	def test_transfer_failure_returns_to_active(self):
		out = domains.register_domain(self.customer, "example-tfail.com")
		domains.REGISTRAR_FAULTS["transfer"] = "registry busy"
		res = domains.transfer_domain(out["domain"], "auth-123")
		self.assertIn("error", res)
		doc = frappe.get_doc("Hosting Domain", out["domain"])
		self.assertEqual(doc.status, "Active")
		self.assertEqual(doc.transfer_status, "Failed")
		domains.REGISTRAR_FAULTS.clear()

	def test_nameservers(self):
		out = domains.register_domain(self.customer, "example-ns.com")
		res = domains.update_nameservers(out["domain"], ["ns1.test.io", "ns2.test.io"])
		self.assertIn("ns1.test.io", res["nameservers"])
		bad = domains.update_nameservers(out["domain"], ["only-one.io"])
		self.assertIn("error", bad)

	def test_dns_crud_and_guards(self):
		out = domains.register_domain(self.customer, "example-dns.com")
		rec = domains.add_dns_record(out["domain"], "A", "www", "203.0.113.10")
		self.assertEqual(rec.status, "Active")
		with self.assertRaises(frappe.ValidationError):
			domains.add_dns_record(out["domain"], "A", "www", "203.0.113.10")
		with self.assertRaises(frappe.ValidationError):
			domains.add_dns_record(out["domain"], "CNAME", "@", "alias.example.")
		with self.assertRaises(frappe.ValidationError):
			domains.add_dns_record(out["domain"], "MX", "@", "mail.example.", priority=0)
		mx = domains.add_dns_record(out["domain"], "MX", "@", "mail.example.", priority=10)
		off = domains.remove_dns_record(mx.name)
		self.assertEqual(off["status"], "Inactive")

	def test_reminders_and_auto_renew(self):
		out = domains.register_domain(self.customer, "example-remind.com")
		frappe.db.set_value("Hosting Domain", out["domain"], "expiry_date", add_days(today(), 7))
		ran = domains.process_domain_renewals()
		self.assertGreaterEqual(ran["reminded"], 1)
		self.assertEqual(frappe.db.get_value("Hosting Domain", out["domain"], "last_reminder_stage"), "7")
		self.assertIsNotNone(frappe.db.get_value("Hosting Domain", out["domain"], "renewal_invoice"))

	def test_expiry_progression(self):
		out = domains.register_domain(self.customer, "example-expire.com")
		frappe.db.set_value("Hosting Domain", out["domain"],
							{"expiry_date": add_days(today(), -1), "auto_renew": 0})
		domains.process_domain_renewals()
		self.assertEqual(frappe.db.get_value("Hosting Domain", out["domain"], "status"), "Expired")
		frappe.db.set_value("Hosting Domain", out["domain"], "expiry_date", add_days(today(), -31))
		domains.process_domain_renewals()
		self.assertEqual(frappe.db.get_value("Hosting Domain", out["domain"], "status"), "Grace Period")
		frappe.db.set_value("Hosting Domain", out["domain"], "expiry_date", add_days(today(), -61))
		domains.process_domain_renewals()
		self.assertEqual(frappe.db.get_value("Hosting Domain", out["domain"], "status"), "Redemption")
		frappe.db.set_value("Hosting Domain", out["domain"], "expiry_date", add_days(today(), -91))
		domains.process_domain_renewals()
		self.assertEqual(frappe.db.get_value("Hosting Domain", out["domain"], "status"), "Terminated")


class TestCertificates(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.customer = ensure_customer(ensure_user())
		self.product = ensure_product()
		self.service = make_service(self.customer, self.product)
		reg = domains.register_domain(self.customer, "example-cert.com", service=self.service.name)
		self.domain = reg["domain"]

	def tearDown(self):
		wipe()

	def test_dns_validation_flow(self):
		req = certificates.request_certificate(self.domain, self.customer, service=self.service.name)
		self.assertEqual(req["status"], "Pending Validation")
		bad = certificates.validate_certificate(req["certificate"])
		self.assertEqual(bad["status"], "Failed")
		domains.add_dns_record(self.domain, "TXT", "_acme-challenge", req["validation_token"])
		good = certificates.validate_certificate(req["certificate"])
		self.assertEqual(good["status"], "Active")
		self.assertIsNotNone(frappe.db.get_value("SSL Certificate", req["certificate"], "expires_at"))

	def test_install_target_must_match_customer(self):
		req = certificates.request_certificate(self.domain, self.customer, validation_method="HTTP")
		certificates.validate_certificate(req["certificate"])
		other_user = ensure_user("phase9-other@example.com")
		other_customer = ensure_customer(other_user)
		other_svc = make_service(other_customer, self.product)
		with self.assertRaises(frappe.ValidationError):
			certificates.install_certificate(req["certificate"], other_svc.name)
		ok = certificates.install_certificate(req["certificate"], self.service.name)
		self.assertEqual(ok["service"], self.service.name)

	def test_renewal_and_failed_renewal(self):
		req = certificates.request_certificate(self.domain, self.customer, validation_method="HTTP")
		certificates.validate_certificate(req["certificate"])
		first_expiry = frappe.db.get_value("SSL Certificate", req["certificate"], "expires_at")
		out = certificates.renew_certificate(req["certificate"])
		self.assertEqual(out["status"], "Active")
		self.assertGreaterEqual(
			str(frappe.db.get_value("SSL Certificate", req["certificate"], "expires_at")), str(first_expiry))
		certificates.CERT_FAULTS["renew"] = "CA unreachable"
		bad = certificates.renew_certificate(req["certificate"])
		self.assertEqual(bad["status"], "Failed")
		certificates.CERT_FAULTS.clear()

	def test_monitor_auto_renews_and_expires(self):
		req = certificates.request_certificate(self.domain, self.customer, validation_method="HTTP")
		certificates.validate_certificate(req["certificate"])
		frappe.db.set_value("SSL Certificate", req["certificate"], "expires_at", add_days(today(), 10))
		ran = certificates.monitor_certificates()
		self.assertEqual(ran["renewed"], 1)
		self.assertEqual(frappe.db.get_value("SSL Certificate", req["certificate"], "status"), "Active")
		frappe.db.set_value("SSL Certificate", req["certificate"],
							{"expires_at": add_days(today(), -1), "auto_renew": 0})
		ran = certificates.monitor_certificates()
		self.assertEqual(ran["expired"], 1)

	def test_stale_validation_fails(self):
		req = certificates.request_certificate(self.domain, self.customer)
		frappe.db.set_value("SSL Certificate", req["certificate"], "creation", add_days(today(), -9))
		ran = certificates.monitor_certificates()
		self.assertEqual(ran["stale"], 1)
		self.assertEqual(frappe.db.get_value("SSL Certificate", req["certificate"], "status"), "Failed")


class TestBackups(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.customer = ensure_customer(ensure_user())
		self.product = ensure_product()
		self.service = make_service(self.customer, self.product)
		self.policy = frappe.get_doc(
			{
				"doctype": "Backup Policy",
				"policy_name": "Phase9 Daily",
				"service": self.service.name,
				"frequency": "Daily",
				"retention_count": 3,
				"retention_days": 30,
				"storage_location": "local",
				"enabled": 1,
			}
		).insert().name

	def tearDown(self):
		wipe()

	def test_run_backup_success_and_failure(self):
		out = backups.run_backup(self.policy)
		self.assertEqual(out["status"], "Completed")
		doc = frappe.get_doc("Service Backup", out["backup"])
		self.assertGreater(float(doc.size_mb), 0)
		self.assertIsNotNone(doc.retain_until)
		backups.BACKUP_FAULTS["run"] = "disk full"
		bad = backups.run_backup(self.policy)
		self.assertEqual(bad["status"], "Failed")
		backups.BACKUP_FAULTS.clear()

	def test_retention_expiry_and_count_trim(self):
		first = backups.run_backup(self.policy)["backup"]
		frappe.db.set_value("Service Backup", first, "retain_until", add_days(today(), -1))
		for _ in range(4):
			backups.run_backup(self.policy)
		ran = backups.enforce_retention()
		self.assertGreaterEqual(ran["expired"], 2, "one aged out plus over-count trims")
		self.assertEqual(
			len(frappe.get_all("Service Backup", {"policy": self.policy, "status": "Completed"})), 3)

	def test_restore_authorization_flow(self):
		bid = backups.run_backup(self.policy)["backup"]
		req = backups.request_restore(bid, self.service.name)["restore"]
		self.assertEqual(frappe.db.get_value("Restore Request", req, "status"), "Pending")
		done = backups.approve_restore(req, note="customer confirmed")
		self.assertEqual(done["status"], "Completed")
		self.assertEqual(frappe.db.get_value("Restore Request", req, "approved_by"), "Administrator")

	def test_restore_failure_can_reapprove(self):
		bid = backups.run_backup(self.policy)["backup"]
		req = backups.request_restore(bid, self.service.name)["restore"]
		backups.BACKUP_FAULTS["restore"] = "target locked"
		bad = backups.approve_restore(req)
		self.assertEqual(bad["status"], "Failed")
		backups.BACKUP_FAULTS.clear()
		good = backups.approve_restore(req)
		self.assertEqual(good["status"], "Completed")

	def test_restore_guards(self):
		bid = backups.run_backup(self.policy)["backup"]
		backups.BACKUP_FAULTS["run"] = "boom"
		failed_bid = backups.run_backup(self.policy)["backup"]
		backups.BACKUP_FAULTS.clear()
		with self.assertRaises(frappe.ValidationError):
			backups.request_restore(failed_bid, self.service.name)
		req = backups.request_restore(bid, self.service.name)["restore"]
		denied = backups.reject_restore(req, note="no consent")
		self.assertEqual(denied["status"], "Rejected")
		_ = bid

	def test_storage_overage_invoiced_once(self):
		snap = backups.record_storage_usage(self.service.name, used_gb=120, quota_gb=100, overage_rate=2.0)
		self.assertEqual(float(snap.overage_gb), 20)
		ran = backups.process_storage_overage()
		self.assertEqual(ran["invoiced"], 1)
		inv = frappe.db.get_value("Service Storage Usage", snap.name, "overage_invoice")
		self.assertEqual(float(frappe.db.get_value("Hosting Invoice", inv, "total_amount")), 40)
		again = backups.process_storage_overage()
		self.assertEqual(again["invoiced"], 0)
		flat = backups.record_storage_usage(self.service.name, used_gb=50, quota_gb=100, overage_rate=2.0)
		self.assertEqual(float(flat.overage_gb), 0)


class TestAddons(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.customer = ensure_customer(ensure_user())
		self.product = ensure_product()
		self.service = make_service(self.customer, self.product)
		self.row = ensure_addon_row(self.product)

	def tearDown(self):
		wipe()

	def test_provision_and_idempotency(self):
		out = addons.provision_addon(self.service.name, self.row, idempotency_key="ao-1")
		self.assertEqual(out["status"], "Active")
		doc = frappe.get_doc("Service Addon", out["addon"])
		self.assertEqual(float(doc.price), 5)
		self.assertTrue(doc.product_snapshot)
		again = addons.provision_addon(self.service.name, self.row, idempotency_key="ao-1")
		self.assertTrue(again.get("duplicate_request"))

	def test_fulfilment_failure_and_retry(self):
		addons.ADDON_FAULTS["fulfill"] = "hypervisor refused"
		out = addons.provision_addon(self.service.name, self.row, idempotency_key="ao-f")
		self.assertEqual(out["status"], "Failed")
		self.assertTrue(frappe.get_all("Resource Cleanup Task", {"service": self.service.name}))
		addons.ADDON_FAULTS.clear()
		retried = addons.retry_addon(out["addon"])
		self.assertEqual(retried["status"], "Active")

	def test_renewal_invoice_then_extend(self):
		out = addons.provision_addon(self.service.name, self.row, idempotency_key="ao-r")
		first = addons.renew_addon(out["addon"])
		self.assertFalse(first["paid"])
		mark_paid(first["invoice"])
		before = frappe.db.get_value("Service Addon", out["addon"], "current_period_end")
		second = addons.renew_addon(out["addon"])
		self.assertTrue(second["paid"])
		after = frappe.db.get_value("Service Addon", out["addon"], "current_period_end")
		self.assertGreaterEqual(str(after), str(before))

	def test_cancel_modes(self):
		now_out = addons.provision_addon(self.service.name, self.row, idempotency_key="ao-c1")
		res = addons.cancel_addon(now_out["addon"], mode="Immediate")
		self.assertEqual(res["status"], "Cancelled")
		eop = addons.provision_addon(self.service.name, self.row, idempotency_key="ao-c2")
		res = addons.cancel_addon(eop["addon"], mode="End of Period")
		self.assertEqual(res["status"], "Cancellation Pending")
		frappe.db.set_value("Service Addon", eop["addon"], "current_period_end", add_days(today(), -1))
		ran = addons.process_addon_renewals()
		self.assertEqual(ran["cancelled"], 1)

	def test_sync_with_service(self):
		out = addons.provision_addon(self.service.name, self.row, idempotency_key="ao-s")
		updated = addons.sync_addons_for_service(self.service.name, "Suspended")
		self.assertIn(out["addon"], updated)
		self.assertEqual(frappe.db.get_value("Service Addon", out["addon"], "status"), "Suspended")
		addons.sync_addons_for_service(self.service.name, "Active")
		self.assertEqual(frappe.db.get_value("Service Addon", out["addon"], "status"), "Active")
