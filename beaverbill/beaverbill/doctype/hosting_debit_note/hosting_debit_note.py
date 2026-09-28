import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Draft": {"Issued", "Cancelled"},
	"Issued": {"Applied", "Cancelled"},
	"Applied": set(),
	"Cancelled": set(),
}


class HostingDebitNote(Document):
	def validate(self):
		if self.amount is not None and float(self.amount) <= 0:
			frappe.throw("Debit note amount must be positive", frappe.ValidationError)
		if self.is_new():
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Debit note cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
