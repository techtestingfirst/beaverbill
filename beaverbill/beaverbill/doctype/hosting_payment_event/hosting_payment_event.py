import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Received": {"Validated", "Failed", "Duplicate"},
	"Validated": {"Processed", "Failed", "Ignored"},
	"Processed": set(),
	"Failed": {"Validated", "Processed"},
	"Duplicate": set(),
	"Ignored": set(),
}


class HostingPaymentEvent(Document):
	def validate(self):
		if self.is_new():
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Event status cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
