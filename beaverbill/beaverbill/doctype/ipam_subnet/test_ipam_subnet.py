import frappe
import unittest

class TestIPAMSubnet(unittest.TestCase):
	def setUp(self):
		frappe.db.delete("IPAM IP Address")
		frappe.db.delete("IPAM Subnet")
		frappe.db.delete("Hosting Provider Account")
		frappe.db.delete("Server Node")
		frappe.db.delete("Datacenter Asset")

	def test_subnet_and_ip_generation(self):
		subnet = frappe.get_doc({
			"doctype": "IPAM Subnet",
			"subnet_name": "Test Subnet",
			"cidr": "192.168.100.0/29",
			"gateway": "192.168.100.1"
		}).insert()

		# /29 has 6 usable hosts (192.168.100.1 to 192.168.100.6)
		ips = frappe.get_all("IPAM IP Address", filters={"subnet": subnet.name})
		self.assertEqual(len(ips), 6)

	def test_infrastructure_creation(self):
		provider = frappe.get_doc({
			"doctype": "Hosting Provider Account",
			"provider_name": "Hetzner Test",
			"provider_type": "Hetzner Cloud"
		}).insert()

		node = frappe.get_doc({
			"doctype": "Server Node",
			"node_name": "Node 1",
			"provider_account": provider.name,
			"node_type": "Hypervisor"
		}).insert()

		asset = frappe.get_doc({
			"doctype": "Datacenter Asset",
			"asset_name": "Rack A1",
			"asset_type": "Rack"
		}).insert()

		self.assertTrue(frappe.db.exists("Hosting Provider Account", provider.name))
		self.assertTrue(frappe.db.exists("Server Node", node.name))
		self.assertTrue(frappe.db.exists("Datacenter Asset", asset.name))
