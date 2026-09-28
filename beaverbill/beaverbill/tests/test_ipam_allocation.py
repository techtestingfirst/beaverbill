import frappe
from frappe.tests import IntegrationTestCase

from beaverbill.beaverbill.doctype.ipam_ip_address.ipam_ip_address import allocate_ip, release_ip


class TestIPAMAllocation(IntegrationTestCase):
	def tearDown(self):
		for ip in frappe.get_all("IPAM IP Address", filters={"status": "Allocated"}, pluck="name"):
			try:
				release_ip(ip)
			except frappe.ValidationError:
				pass

	def make_subnet(self, name, cidr, **kwargs):
		doc = frappe.get_doc({"doctype": "IPAM Subnet", "subnet_name": name, "cidr": cidr, **kwargs})
		doc.insert()
		return doc

	def test_invalid_cidr_rejected(self):
		self.assertRaises(
			frappe.ValidationError, self.make_subnet, "Bad CIDR Subnet", "not-a-network"
		)

	def test_gateway_outside_network_rejected(self):
		self.assertRaises(
			frappe.ValidationError,
			self.make_subnet,
			"Bad Gateway Subnet",
			"10.20.0.0/24",
			gateway="10.99.0.1",
		)

	def test_vlan_range_enforced(self):
		self.assertRaises(
			frappe.ValidationError, self.make_subnet, "Bad VLAN Subnet", "10.21.0.0/24", vlan_id=5000
		)

	def test_ipv6_subnet_generates_versioned_ips(self):
		subnet = self.make_subnet("Phase1 v6", "fd00:1::/126")
		try:
			self.assertEqual(subnet.ip_version, "IPv6")
			ips = frappe.get_all("IPAM IP Address", filters={"subnet": subnet.name}, pluck="ip_version")
			self.assertEqual(len(ips), 3)
			self.assertEqual(set(ips), {"IPv6"})
		finally:
			frappe.db.delete("IPAM IP Address", {"subnet": subnet.name})
			frappe.db.delete("IPAM Subnet", subnet.name)

	def test_allocate_and_release_lifecycle(self):
		subnet = self.make_subnet("Phase1 Life", "10.30.0.0/29")
		try:
			ip_name = allocate_ip(
				subnet=subnet.name,
				reference_doctype="Hosting Subscription",
				reference_name="SUB-001",
			)
			doc = frappe.get_doc("IPAM IP Address", ip_name)
			self.assertEqual(doc.status, "Allocated")
			self.assertEqual(doc.allocated_to_name, "SUB-001")
			self.assertIsNotNone(doc.allocated_at)
			log = frappe.db.exists(
				"IPAM Allocation Log", {"ip_address": ip_name, "action": "Allocated"}
			)
			self.assertTrue(log)
			release_ip(ip_name)
			doc.reload()
			self.assertEqual(doc.status, "Available")
			self.assertFalse(doc.allocated_to_name)
		finally:
			frappe.db.delete("IPAM IP Address", {"subnet": subnet.name})
			frappe.db.delete("IPAM Subnet", subnet.name)

	def test_exhaustion_raises(self):
		subnet = self.make_subnet("Phase1 Small", "10.31.0.0/30")
		try:
			allocate_ip(subnet=subnet.name)
			allocate_ip(subnet=subnet.name)
			self.assertRaises(frappe.ValidationError, allocate_ip, subnet=subnet.name)
		finally:
			frappe.db.delete("IPAM IP Address", {"subnet": subnet.name})
			frappe.db.delete("IPAM Subnet", subnet.name)

	def test_invalid_transition_rejected(self):
		subnet = self.make_subnet("Phase1 Trans", "10.32.0.0/29")
		try:
			ip_name = allocate_ip(subnet=subnet.name)
			doc = frappe.get_doc("IPAM IP Address", ip_name)
			doc.status = "Quarantined"
			self.assertRaises(frappe.ValidationError, doc.save)
		finally:
			frappe.db.delete("IPAM IP Address", {"subnet": subnet.name})
			frappe.db.delete("IPAM Subnet", subnet.name)

	def test_support_cannot_allocate(self):
		subnet = self.make_subnet("Phase1 Guard", "10.33.0.0/29")
		try:
			if not frappe.db.exists("User", "phase1-alloc-support@example.com"):
				frappe.get_doc(
					{
						"doctype": "User",
						"email": "phase1-alloc-support@example.com",
						"first_name": "allocsupport",
						"send_welcome_email": 0,
						"roles": [{"role": "Hosting Support"}],
					}
				).insert(ignore_permissions=True)
			frappe.set_user("phase1-alloc-support@example.com")
			try:
				self.assertRaises(frappe.PermissionError, allocate_ip, subnet=subnet.name)
			finally:
				frappe.set_user("Administrator")
		finally:
			frappe.db.delete("IPAM IP Address", {"subnet": subnet.name})
			frappe.db.delete("IPAM Subnet", subnet.name)

	def test_driver_release_scoped_to_subscription(self):
		from beaverbill.beaverbill.provisioning_drivers import get_provisioning_driver

		subnet = self.make_subnet("Phase1 Driver", "10.34.0.0/29")
		try:
			driver = get_provisioning_driver("Dedicated Server")
			first = driver.provision("SUB-A")
			second = driver.provision("SUB-B")
			self.assertIsNotNone(first["ip"])
			self.assertIsNotNone(second["ip"])
			self.assertNotEqual(first["ip"], second["ip"])
			driver.terminate("SUB-A")
			a = frappe.db.get_all(
				"IPAM IP Address",
				filters={"allocated_to_name": "SUB-A", "status": "Allocated"},
			)
			b = frappe.db.get_all(
				"IPAM IP Address",
				filters={"allocated_to_name": "SUB-B", "status": "Allocated"},
			)
			self.assertEqual(len(a), 0)
			self.assertEqual(len(b), 1)
		finally:
			frappe.db.delete("IPAM IP Address", {"subnet": subnet.name})
			frappe.db.delete("IPAM Subnet", subnet.name)

	def test_reports_execute(self):
		from beaverbill.beaverbill.report.duplicate_ip_allocation.duplicate_ip_allocation import (
			execute as dup_execute,
		)
		from beaverbill.beaverbill.report.ip_pool_exhaustion.ip_pool_exhaustion import execute as pool_execute

		columns, data = pool_execute()
		self.assertTrue(columns)
		self.assertIsInstance(data, list)
		columns, data = dup_execute()
		self.assertTrue(columns)
		self.assertIsInstance(data, list)

	def test_phase1_patch_idempotent(self):
		from beaverbill.patches.phase1_infra_roles_and_ip_version import execute

		execute()
		execute()
		for role in ("Hosting Admin", "Hosting Support", "Hosting Customer"):
			self.assertTrue(frappe.db.exists("Role", role))
