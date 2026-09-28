import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Pending": {"Done", "Failed", "Skipped"},
	"Failed": {"Pending", "Skipped"},
	"Done": set(),
	"Skipped": set(),
}


class ResourceCleanupTask(Document):
	def validate(self):
		if self.is_new():
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Resource Cleanup Task cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
			if self.status in ("Done", "Skipped") and not self.completed_at:
				self.completed_at = frappe.utils.now_datetime()
