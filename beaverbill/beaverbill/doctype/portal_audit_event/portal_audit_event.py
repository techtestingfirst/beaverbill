import frappe
from frappe.model.document import Document


class PortalAuditEvent(Document):
	def validate(self):
		# Audit events are append-only; only fresh inserts are valid.
		if not self.is_new():
			previous = self.get_db_value("endpoint")
			if previous and self.endpoint and previous != self.endpoint:
				frappe.throw("Portal Audit Events are immutable", frappe.ValidationError)
		if not self.at:
			self.at = frappe.utils.now_datetime()
