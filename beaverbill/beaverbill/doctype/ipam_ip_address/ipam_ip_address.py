import ipaddress

import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Available": {"Reserved", "Allocated", "Quarantined"},
	"Reserved": {"Available", "Allocated", "Quarantined"},
	"Allocated": {"Available", "Released"},
	"Released": {"Available", "Allocated", "Quarantined"},
	"Quarantined": {"Available"},
}

ALLOCATE_ROLES = {"System Manager", "Hosting Admin"}


def _require_allocate_role() -> None:
	roles = set(frappe.get_roles())
	if not roles.intersection(ALLOCATE_ROLES):
		frappe.throw("Only Hosting Admin can allocate or release IP addresses", frappe.PermissionError)


def _log_allocation(ip_name: str, action: str, ref_doctype: str | None, ref_name: str | None) -> None:
	frappe.get_doc(
		{
			"doctype": "IPAM Allocation Log",
			"ip_address": ip_name,
			"action": action,
			"reference_doctype": ref_doctype or "",
			"reference_name": ref_name or "",
		}
	).insert(ignore_permissions=True)


class IPAMIPAddress(Document):
	def validate(self):
		try:
			addr = ipaddress.ip_address(self.ip_address)
		except ValueError:
			frappe.throw(f"Invalid IP address: {self.ip_address}", frappe.ValidationError)
			return
		self.ip_version = f"IPv{addr.version}"
		cidr = frappe.db.get_value("IPAM Subnet", self.subnet, "cidr")
		if cidr:
			try:
				if addr not in ipaddress.ip_network(cidr, strict=False):
					frappe.throw(
						f"IP {self.ip_address} is not inside subnet {cidr}", frappe.ValidationError
					)
			except ValueError:
				frappe.throw(f"Subnet has invalid CIDR: {cidr}", frappe.ValidationError)
		if self.is_new():
			if self.status not in {"Available", "Reserved"}:
				frappe.throw("New IP addresses must start as Available or Reserved", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status and self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
			frappe.throw(f"IP status cannot move from {previous} to {self.status}", frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
def allocate_ip(
	subnet: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> str:
	"""Allocate one Available IP, locking the row against concurrent allocators."""
	_require_allocate_role()
	filters = {"status": "Available"}
	if subnet:
		filters["subnet"] = subnet
	rows = frappe.db.get_values(
		"IPAM IP Address",
		filters,
		"name",
		order_by="creation asc",
		for_update=True,
	)
	if not rows:
		frappe.throw("IP pool exhausted: no Available address", frappe.ValidationError)
	doc = frappe.get_doc("IPAM IP Address", rows[0][0])
	doc.status = "Allocated"
	doc.allocated_to_doctype = reference_doctype or ""
	doc.allocated_to_name = reference_name or ""
	doc.allocated_at = frappe.utils.now_datetime()
	doc.save(ignore_permissions=True)
	_log_allocation(doc.name, "Allocated", reference_doctype, reference_name)
	return doc.name


@frappe.whitelist(methods=["POST"])
def release_ip(ip_name: str) -> str:
	"""Return an Allocated IP to the Available pool."""
	_require_allocate_role()
	doc = frappe.get_doc("IPAM IP Address", ip_name)
	if doc.status != "Allocated":
		frappe.throw(f"Only Allocated IPs can be released (found {doc.status})", frappe.ValidationError)
	doc.status = "Available"
	doc.allocated_to_doctype = ""
	doc.allocated_to_name = ""
	doc.allocated_at = None
	doc.save(ignore_permissions=True)
	_log_allocation(doc.name, "Released", None, None)
	return doc.name


@frappe.whitelist(methods=["GET"])
def get_pool_stats(subnet: str | None = None) -> list[dict]:
	"""Per-subnet pool totals for the exhaustion report. Staff only."""
	roles = set(frappe.get_roles())
	if not roles.intersection(ALLOCATE_ROLES) and "Hosting Support" not in roles:
		frappe.throw("Not permitted to view IP pool stats", frappe.PermissionError)
	filters = {"subnet": subnet} if subnet else {}
	rows = frappe.db.get_all(
		"IPAM IP Address",
		filters=filters,
		fields=["subnet", "status", {"COUNT": "name", "as": "total"}],
		group_by="subnet, status",
	)
	return rows
