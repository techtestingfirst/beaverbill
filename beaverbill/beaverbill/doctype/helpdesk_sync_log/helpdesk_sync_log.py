import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Pending": {"In Progress", "Synced", "Failed"},
	"In Progress": {"Synced", "Failed", "Pending"},
	"Synced": set(),
	"Failed": {"Pending"},
}


class HelpdeskSyncLog(Document):
	def validate(self):
		if self.is_new():
			if self.status not in ("Pending", "In Progress"):
				frappe.throw("New sync rows must start as Pending or In Progress", frappe.ValidationError)
			if not self.idempotency_key:
				frappe.throw("Idempotency Key is required", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Sync Log cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
