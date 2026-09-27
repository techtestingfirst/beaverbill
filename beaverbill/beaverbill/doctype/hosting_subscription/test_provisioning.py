import frappe
import unittest
from beaverbill.beaverbill.provisioning_drivers import get_provisioning_driver

class TestProvisioningDrivers(unittest.TestCase):
	def setUp(self):
		frappe.db.delete("IPAM IP Address")
		frappe.db.delete("IPAM Subnet")

		# Setup a subnet and IP for Dedicated Server driver testing
		self.subnet = frappe.get_doc({
			"doctype": "IPAM Subnet",
			"subnet_name": "Test Subnet",
			"cidr": "192.168.100.0/29",
			"gateway": "192.168.100.1"
		}).insert()

	def test_cpanel_driver(self):
		driver = get_provisioning_driver("cPanel/WHM")
		res = driver.provision("SUB-0001")
		self.assertEqual(res["status"], "Success")
		self.assertTrue(res["username"].startswith("user_"))

		self.assertEqual(driver.suspend("SUB-0001")["status"], "Success")
		self.assertEqual(driver.unsuspend("SUB-0001")["status"], "Success")
		self.assertEqual(driver.resize("SUB-0001", "VPS Pro")["status"], "Success")
		self.assertEqual(driver.terminate("SUB-0001")["status"], "Success")

	def test_proxmox_driver(self):
		driver = get_provisioning_driver("Proxmox VE")
		res = driver.provision("SUB-0002")
		self.assertEqual(res["status"], "Success")
		self.assertEqual(res["vmid"], 1001)

		self.assertEqual(driver.reboot("SUB-0002")["status"], "Success")
		self.assertEqual(driver.get_vnc_console("SUB-0002")["status"], "Success")
		self.assertTrue("console=vnc" in driver.get_vnc_console("SUB-0002")["url"])

	def test_dedicated_server_ipam_driver(self):
		driver = get_provisioning_driver("Dedicated Server")
		res = driver.provision("SUB-0003")
		self.assertEqual(res["status"], "Success")
		self.assertIsNotNone(res["ip"])

		# Verify IP status is Allocated
		allocated_ips = frappe.get_all("IPAM IP Address", filters={"status": "Allocated"})
		self.assertEqual(len(allocated_ips), 1)

		# Terminate and verify IP is released back to Available
		driver.terminate("SUB-0003")
		allocated_ips_after = frappe.get_all("IPAM IP Address", filters={"status": "Allocated"})
		self.assertEqual(len(allocated_ips_after), 0)
