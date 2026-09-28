import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Pending": {"Queued", "Cancelled"},
	"Queued": {"Running", "Retrying", "Failed", "Manual Review", "Cancelled"},
	"Running": {"Succeeded", "Failed", "Retrying", "Manual Review"},
	"Retrying": {"Queued", "Running", "Cancelled", "Manual Review"},
	"Failed": {"Retrying", "Manual Review", "Compensated"},
	"Manual Review": {"Retrying", "Queued", "Compensated", "Cancelled"},
	"Succeeded": {"Compensated"},
	"Compensated": set(),
	"Cancelled": set(),
}


class ProvisioningOperation(Document):
	def validate(self):
		if self.is_new():
			if self.status not in ("Pending", "Queued"):
				frappe.throw("New provisioning operations must start as Pending or Queued", frappe.ValidationError)
			if not self.idempotency_key:
				frappe.throw("Idempotency Key is required", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Provisioning Operation cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)


def process_queued_provisioning_operations():
	"""Scheduler entry point; delegates to the Phase 8 engine."""
	from beaverbill.beaverbill import provisioning

	return provisioning.process_queued_operations()
