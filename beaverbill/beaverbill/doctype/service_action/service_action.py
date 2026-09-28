import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Pending": {"In Progress", "Completed", "Failed"},
	"In Progress": {"Completed", "Failed"},
	"Completed": set(),
	"Failed": set(),
}


class ServiceAction(Document):
	def validate(self):
		if self.is_new():
			if self.status != "Pending":
				frappe.throw("New service actions must start as Pending", frappe.ValidationError)
			if not self.idempotency_key:
				frappe.throw("Idempotency Key is required", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Service Action cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
