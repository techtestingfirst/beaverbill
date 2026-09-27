import frappe
from frappe.model.document import Document
import ipaddress

class IPAMSubnet(Document):
	def after_insert(self):
		# Automatically generate IP addresses for the subnet
		try:
			net = ipaddress.ip_network(self.cidr, strict=False)
			# Limit generation to /24 or smaller to avoid huge DB inserts
			if net.num_addresses <= 256:
				for ip in net.hosts():
					frappe.get_doc({
						"doctype": "IPAM IP Address",
						"ip_address": str(ip),
						"subnet": self.name,
						"status": "Available"
					}).insert(ignore_permissions=True)
		except Exception:
			pass
