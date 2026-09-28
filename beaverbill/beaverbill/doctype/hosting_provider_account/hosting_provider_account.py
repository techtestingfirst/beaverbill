import frappe
from frappe.model.document import Document

class HostingProviderAccount(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Password | None
		api_secret: DF.Password | None
		endpoint_url: DF.Data | None
		provider_name: DF.Data
		provider_type: DF.Literal["Hetzner Cloud", "OVHcloud", "cPanel/WHM", "DirectAdmin", "Proxmox VE", "Custom"]
	# end: auto-generated types

	@frappe.whitelist()
	def get_public_fields(self) -> dict:
		"""Return account fields safe for desk display. Never includes secrets."""
		if not set(frappe.get_roles()).intersection({"System Manager", "Hosting Admin", "Hosting Support"}):
			frappe.throw("Not permitted to view provider accounts", frappe.PermissionError)
		return {
			"name": self.name,
			"provider_name": self.provider_name,
			"provider_type": self.provider_type,
			"endpoint_url": self.endpoint_url,
		}
