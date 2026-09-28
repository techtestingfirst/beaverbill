import ipaddress

import frappe
from frappe.model.document import Document


class IPAMSubnet(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		cidr: DF.Data
		dns_servers: DF.Text | None
		gateway: DF.Data | None
		ip_version: DF.Literal["IPv4", "IPv6"]
		subnet_name: DF.Data
		vlan_id: DF.Int | None
	# end: auto-generated types

	def validate(self):
		try:
			net = ipaddress.ip_network(self.cidr, strict=False)
		except ValueError:
			frappe.throw(f"Invalid CIDR: {self.cidr}", frappe.ValidationError)
			return
		self.ip_version = f"IPv{net.version}"
		if self.gateway:
			try:
				gateway_ip = ipaddress.ip_address(self.gateway)
			except ValueError:
				frappe.throw(f"Invalid gateway IP: {self.gateway}", frappe.ValidationError)
			if gateway_ip not in net:
				frappe.throw(f"Gateway {self.gateway} is not inside {self.cidr}", frappe.ValidationError)
		if self.vlan_id:
			if not 1 <= int(self.vlan_id) <= 4094:
				frappe.throw("VLAN ID must be between 1 and 4094", frappe.ValidationError)

	def after_insert(self):
		# Generate one IPAM IP Address per host. Existing behavior kept:
		# all hosts() are created, including the gateway address.
		try:
			net = ipaddress.ip_network(self.cidr, strict=False)
		except ValueError:
			return
		# Limit generation to avoid huge DB inserts (covers IPv6).
		if net.num_addresses > 256:
			return
		version = f"IPv{net.version}"
		for ip in net.hosts():
			ip_str = str(ip)
			if frappe.db.exists("IPAM IP Address", ip_str):
				continue
			frappe.get_doc(
				{
					"doctype": "IPAM IP Address",
					"ip_address": ip_str,
					"subnet": self.name,
					"ip_version": version,
					"status": "Available",
				}
			).insert(ignore_permissions=True)

	def on_trash(self):
		in_use = frappe.db.count(
			"IPAM IP Address", {"subnet": self.name, "status": ["!=", "Available"]}
		)
		if in_use:
			frappe.throw(
				f"Cannot delete subnet {self.name}: {in_use} IP(s) are not Available",
				frappe.ValidationError,
			)
		frappe.db.delete("IPAM IP Address", {"subnet": self.name})
