import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Draft": {"Issued", "Cancelled"},
	"Issued": {"Applied", "Cancelled"},
	"Applied": set(),
	"Cancelled": set(),
}


class HostingCreditNote(Document):
	def validate(self):
		if self.amount is not None and float(self.amount) <= 0:
			frappe.throw("Credit note amount must be positive", frappe.ValidationError)
		if self.is_new():
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Credit note cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
