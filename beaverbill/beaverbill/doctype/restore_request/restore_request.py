import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Pending": {"Approved", "Rejected"},
	"Approved": {"In Progress", "Rejected"},
	"In Progress": {"Completed", "Failed"},
	"Completed": set(),
	"Failed": {"Approved"},
	"Rejected": set(),
}


class RestoreRequest(Document):
	def validate(self):
		if self.is_new():
			if self.status != "Pending":
				frappe.throw("New restore requests must start as Pending", frappe.ValidationError)
			if not self.requested_by:
				self.requested_by = frappe.session.user
			backup_status = frappe.db.get_value("Service Backup", self.backup, "status")
			if backup_status != "Completed":
				frappe.throw(
					f"Only Completed backups can be restored, not {backup_status}",
					frappe.ValidationError,
				)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Restore Request cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
			if self.status in ("Completed", "Rejected") and not self.completed_at:
				self.completed_at = frappe.utils.now_datetime()
