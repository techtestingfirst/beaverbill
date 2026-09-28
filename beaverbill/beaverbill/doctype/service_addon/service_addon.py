import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Pending": {"Active", "Failed", "Cancelled"},
	"Active": {"Suspended", "Cancellation Pending", "Cancelled"},
	"Suspended": {"Active", "Cancellation Pending", "Cancelled"},
	"Cancellation Pending": {"Cancelled", "Active"},
	"Failed": {"Pending", "Cancelled"},
	"Cancelled": set(),
}


class ServiceAddon(Document):
	def validate(self):
		if self.is_new():
			if self.status not in ("Pending", "Active"):
				frappe.throw("New service addons must start as Pending or Active", frappe.ValidationError)
			if not self.idempotency_key:
				frappe.throw("Idempotency Key is required", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Service Addon cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)


def process_addon_renewals(as_of=None):
	"""Scheduler entry point; delegates to the Phase 9 engine."""
	from beaverbill.beaverbill import addons

	return addons.process_addon_renewals(as_of=as_of)
