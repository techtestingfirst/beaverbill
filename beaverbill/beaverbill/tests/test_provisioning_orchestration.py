"""Phase 8 tests: driver contract, orchestration, retries, reconciliation."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from beaverbill.beaverbill import provisioning
from beaverbill.beaverbill import provisioning_drivers as drivers
from beaverbill.beaverbill.provisioning_drivers import (
	DRIVER_CONTRACT_VERSION,
	BaseProvisioningDriver,
	ProvisioningError,
	call_driver_action,
	classify_exception,
)


class FlakyDriver(BaseProvisioningDriver):
	failures_left = 0

	def provision(self, subscription_name, details=None):
		if FlakyDriver.failures_left > 0:
			FlakyDriver.failures_left -= 1
			raise ConnectionError("temporary connection reset")
		return {"status": "Success", "server": "srv-1"}

	def suspend(self, subscription_name):
		return {"status": "Success"}

	def unsuspend(self, subscription_name):
		return {"status": "Success"}

	def terminate(self, subscription_name):
		return {"status": "Success"}

	def resize(self, subscription_name, new_product_name):
		return {"status": "Success"}


class PermanentDriver(BaseProvisioningDriver):
	def provision(self, subscription_name, details=None):
		raise ValueError("invalid plan: not found")

	def suspend(self, subscription_name):
		return {"status": "Success"}

	def unsuspend(self, subscription_name):
		return {"status": "Success"}

	def terminate(self, subscription_name):
		return {"status": "Success"}

	def resize(self, subscription_name, new_product_name):
		return {"status": "Success"}


class MysteryBlastDriver(BaseProvisioningDriver):
	"""Terminate explodes with an unclassifiable error (unknown outcome)."""

	def provision(self, subscription_name, details=None):
		return {"status": "Success"}

	def suspend(self, subscription_name):
		return {"status": "Success"}

	def unsuspend(self, subscription_name):
		return {"status": "Success"}

	def terminate(self, subscription_name):
		raise RuntimeError("!!! panel exploded !!!")

	def resize(self, subscription_name, new_product_name):
		return {"status": "Success"}


class DescribingDriver(FlakyDriver):
	remote = {"status": "Active"}

	def describe(self, subscription_name):
		return dict(DescribingDriver.remote)


def wipe():
	for dt in [
		"Resource Cleanup Task",
		"Reconciliation Result",
		"Provider Request Log",
		"Provisioning Attempt",
		"Provisioning Operation",
		"Hosting Service",
		"Hosting Subscription",
		"Hosting Product",
		"Server Node",
		"Hosting Provider Account",
	]:
		for name in frappe.get_all(dt, pluck="name"):
			frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
	frappe.db.commit()


def ensure_user(email="phase8-buyer@example.com"):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Phase8", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return email


def ensure_customer(user):
	name = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	if name:
		return name
	return frappe.get_doc(
		{"doctype": "Hosting Customer", "customer_name": "Phase8 Buyer",
		 "primary_user": user, "status": "Active"}
	).insert().name


def ensure_product(name="Phase8 Small"):
	if not frappe.db.exists("Hosting Product Group", "Phase8 Group"):
		frappe.get_doc({"doctype": "Hosting Product Group", "product_group_name": "Phase8 Group"}).insert()
	if frappe.db.exists("Hosting Product", name):
		return name
	return frappe.get_doc(
		{
			"doctype": "Hosting Product",
			"product_name": name,
			"product_group": "Phase8 Group",
			"billing_cycle": "Monthly",
			"price": 10,
			"currency": "USD",
		}
	).insert().name


def make_service(customer, product, **over):
	doc = {
		"doctype": "Hosting Service",
		"customer": customer,
		"status": "Pending",
		"product": product,
		"billing_cycle": "Monthly",
	}
	doc.update(over)
	return frappe.get_doc(doc).insert()


class TestDriverContract(IntegrationTestCase):
	def test_contract_version(self):
		self.assertEqual(BaseProvisioningDriver.contract_version, DRIVER_CONTRACT_VERSION)
		self.assertEqual(DRIVER_CONTRACT_VERSION, "2.0")

	def test_all_registered_drivers_keep_legacy_signatures(self):
		for driver_type in (
			"cPanel/WHM",
			"DirectAdmin",
			"Hetzner Cloud",
			"OVHcloud",
			"Proxmox VE",
			"Dedicated Server",
		):
			driver = drivers.get_provisioning_driver(driver_type)
			for method in ("provision", "suspend", "unsuspend", "terminate", "resize"):
				self.assertTrue(callable(getattr(driver, method, None)), f"{driver_type}.{method}")
			caps = driver.capabilities()
			self.assertEqual(caps["contract_version"], DRIVER_CONTRACT_VERSION)

	def test_unknown_driver_stays_permanent(self):
		with self.assertRaises(ValueError):
			drivers.get_provisioning_driver("Nope")

	def test_classify_exception_table(self):
		self.assertEqual(classify_exception(ConnectionError("timeout"))[0], "transient")
		self.assertEqual(classify_exception(Exception("429 too many requests"))[0], "rate_limited")
		self.assertEqual(classify_exception(Exception("capacity exhausted"))[0], "capacity")
		self.assertEqual(classify_exception(Exception("invalid plan not found"))[0], "permanent")
		self.assertEqual(classify_exception(Exception("!!! panel exploded !!!"))[0], "unknown")

	def test_call_action_normalizes_legacy_dict(self):
		result, elapsed = call_driver_action(FlakyDriver(), "provision", "SUB-1")
		self.assertEqual(result["status"], "Success")
		self.assertGreaterEqual(elapsed, 0)

	def test_call_action_wraps_errors(self):
		with self.assertRaises(ProvisioningError) as ctx:
			call_driver_action(PermanentDriver(), "provision", "SUB-1")
		self.assertEqual(ctx.exception.error_type, "permanent")
		self.assertFalse(ctx.exception.retryable)

	def test_backoff_grows_by_error_type(self):
		short = provisioning.backoff_for("transient", 0)
		self.assertGreater(provisioning.backoff_for("rate_limited", 0), 0)
		self.assertGreater(provisioning.backoff_for("capacity", 0), short)
		self.assertEqual(provisioning.backoff_for("permanent", 0), 0)
		self.assertGreater(provisioning.backoff_for("transient", 2), short)

	def test_should_retry_rules(self):
		self.assertTrue(provisioning.should_retry("Create", "transient", True, 0, 3))
		self.assertFalse(provisioning.should_retry("Create", "permanent", False, 0, 3))
		# Destructive + unknown outcome is never blind-retried.
		self.assertFalse(provisioning.should_retry("Terminate", "unknown", True, 0, 3))
		self.assertFalse(provisioning.should_retry("Create", "transient", True, 3, 3))


class TestOrchestration(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		user = ensure_user()
		self.customer = ensure_customer(user)
		self.product = ensure_product()
		self.account = frappe.get_doc(
			{"doctype": "Hosting Provider Account", "provider_name": "Phase8 Acct", "provider_type": "Proxmox VE"}
		).insert().name
		self._patched = provisioning.get_provisioning_driver
		provisioning.get_provisioning_driver = lambda *a, **k: FlakyDriver()
		FlakyDriver.failures_left = 0
		DescribingDriver.remote = {"status": "Active"}

	def tearDown(self):
		provisioning.get_provisioning_driver = self._patched
		wipe()

	def queue(self, svc, **over):
		args = {
			"service": svc.name,
			"operation_type": "Create",
			"idempotency_key": f"key-{svc.name}-{over.get('operation_type', 'Create')}",
			"max_retries": 3,
			"provider_account": self.account,
		}
		args.update(over)
		return provisioning.queue_operation(**args)

	def test_queue_is_idempotent(self):
		svc = make_service(self.customer, self.product)
		first = self.queue(svc, idempotency_key="idem-1")
		second = provisioning.queue_operation(service=svc.name, operation_type="Create",
											  idempotency_key="idem-1", provider_account=self.account)
		self.assertEqual(first.name, second.name)
		self.assertEqual(len(frappe.get_all("Provisioning Operation", {"idempotency_key": "idem-1"})), 1)

	def test_create_success_activates_service(self):
		svc = make_service(self.customer, self.product)
		op = self.queue(svc, idempotency_key="idem-ok")
		out = provisioning.run_operation(op.name)
		self.assertEqual(out.status, "Succeeded")
		self.assertEqual(frappe.db.get_value("Hosting Service", svc.name, "status"), "Active")
		self.assertEqual(len(frappe.get_all("Provisioning Attempt", {"operation": op.name})), 1)
		self.assertEqual(len(frappe.get_all("Provider Request Log", {"operation": op.name})), 1)

	def test_transient_failure_retries_then_succeeds(self):
		FlakyDriver.failures_left = 1
		svc = make_service(self.customer, self.product)
		op = self.queue(svc, idempotency_key="idem-flaky")
		out = provisioning.run_operation(op.name)
		self.assertEqual(out.status, "Retrying")
		self.assertEqual(int(out.retry_count), 1)
		self.assertIsNotNone(out.next_retry_at)
		out.next_retry_at = None
		out.status = "Queued"
		out.save()
		done = provisioning.run_operation(op.name)
		self.assertEqual(done.status, "Succeeded")
		self.assertEqual(len(frappe.get_all("Provisioning Attempt", {"operation": op.name})), 2)

	def test_permanent_failure_does_not_retry(self):
		provisioning.get_provisioning_driver = lambda *a, **k: PermanentDriver()
		svc = make_service(self.customer, self.product)
		op = self.queue(svc, idempotency_key="idem-perm")
		out = provisioning.run_operation(op.name)
		self.assertEqual(out.status, "Failed")
		self.assertEqual(out.error_type, "permanent")
		tasks = frappe.get_all("Resource Cleanup Task", {"operation": op.name})
		self.assertTrue(tasks)

	def test_destructive_unknown_goes_to_manual_review(self):
		provisioning.get_provisioning_driver = lambda *a, **k: MysteryBlastDriver()
		svc = make_service(self.customer, self.product)
		op = self.queue(svc, operation_type="Terminate", idempotency_key="idem-blast")
		out = provisioning.run_operation(op.name)
		self.assertEqual(out.status, "Manual Review")
		self.assertEqual(out.error_type, "unknown")
		self.assertEqual(int(out.retry_count), 0)

	def test_compensate_creates_cleanup_tasks(self):
		provisioning.get_provisioning_driver = lambda *a, **k: MysteryBlastDriver()
		svc = make_service(self.customer, self.product)
		op = self.queue(svc, operation_type="Terminate", idempotency_key="idem-comp")
		provisioning.run_operation(op.name)
		frappe.set_user("Administrator")
		out = provisioning.compensate_operation(op.name, note="panel checked manually")
		self.assertEqual(out["status"], "Compensated")
		self.assertTrue(out["cleanup_tasks"])

	def test_capacity_block_retries(self):
		node = frappe.get_doc(
			{
				"doctype": "Server Node",
				"node_name": "Phase8 Node",
				"node_type": "Hypervisor",
				"maintenance_mode": 1,
				"maintenance_notes": "rack work",
			}
		).insert()
		svc = make_service(self.customer, self.product, server_node=node.name)
		op = self.queue(svc, idempotency_key="idem-cap")
		out = provisioning.run_operation(op.name)
		self.assertEqual(out.status, "Retrying")
		self.assertEqual(out.error_type, "capacity")

	def test_reconcile_matched_and_mismatched(self):
		svc = make_service(self.customer, self.product)
		svc.status = "Provisioning"
		svc.save(ignore_permissions=True)
		DescribingDriver.remote = {"status": "Active"}
		provisioning.get_provisioning_driver = lambda *a, **k: DescribingDriver()
		svc.provider_account = self.account
		svc.save(ignore_permissions=True)
		mismatch = provisioning.reconcile_service(svc.name)
		self.assertEqual(mismatch.verdict, "Mismatched")
		svc.reload()
		svc.status = "Active"
		svc.save(ignore_permissions=True)
		match = provisioning.reconcile_service(svc.name)
		self.assertEqual(match.verdict, "Matched")

	def test_reconcile_unknown_without_driver(self):
		svc = make_service(self.customer, self.product)
		result = provisioning.reconcile_service(svc.name)
		self.assertEqual(result.verdict, "Unknown")

	def test_orphaned_remote_detected(self):
		svc = make_service(self.customer, self.product)
		for target in ("Provisioning", "Active", "Suspended", "Terminated"):
			svc.reload()
			svc.status = target
			svc.save(ignore_permissions=True)
		result = provisioning.reconcile_service(svc.name, remote_state={"status": "Active"})
		self.assertEqual(result.verdict, "Orphaned Remote")
		orphans = provisioning.orphaned_resources()
		self.assertTrue([r for r in orphans if r.service == svc.name])
