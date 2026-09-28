import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Pending": {"In Progress", "Failed"},
	"In Progress": {"Completed", "Failed"},
	"Completed": {"Expired"},
	"Failed": {"Pending"},
	"Expired": {"Deleted"},
	"Deleted": set(),
}


class ServiceBackup(Document):
	def validate(self):
		if self.is_new():
			if self.status not in ("Pending", "In Progress"):
				frappe.throw("New backups must start as Pending or In Progress", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Backup cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
