import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Created": {"Processed", "Failed"},
	"Processed": {"Chargeback"},
	"Failed": set(),
	"Chargeback": set(),
}


class HostingRefund(Document):
	def validate(self):
		if self.amount is not None and float(self.amount) <= 0:
			frappe.throw("Refund amount must be positive", frappe.ValidationError)
		if self.is_new():
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Refund status cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
