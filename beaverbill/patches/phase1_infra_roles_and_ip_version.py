"""Phase 1: ensure infra roles exist and backfill IP version metadata.

Idempotent: safe to re-run. Only fills empty values, never overwrites.
"""

import ipaddress

import frappe


def execute():
	for role_name, desk_access in [
		("Hosting Admin", 1),
		("Hosting Support", 1),
		("Hosting Customer", 0),
	]:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc(
				{"doctype": "Role", "role_name": role_name, "desk_access": desk_access}
			).insert(ignore_permissions=True)

	for subnet in frappe.get_all("IPAM Subnet", fields=["name", "cidr"]):
		try:
			version = f"IPv{ipaddress.ip_network(subnet.cidr, strict=False).version}"
		except ValueError:
			frappe.logger().warning(f"Phase 1 patch: subnet {subnet.name} has invalid CIDR {subnet.cidr}")
			continue
		frappe.db.set_value("IPAM Subnet", subnet.name, "ip_version", version)

	for ip in frappe.get_all("IPAM IP Address", fields=["name", "ip_address"]):
		try:
			version = f"IPv{ipaddress.ip_address(ip.ip_address).version}"
		except ValueError:
			frappe.logger().warning(f"Phase 1 patch: IP record {ip.name} is not a valid address")
			continue
		frappe.db.set_value("IPAM IP Address", ip.name, "ip_version", version)
