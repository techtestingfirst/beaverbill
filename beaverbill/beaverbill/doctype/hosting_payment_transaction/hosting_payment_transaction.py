import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Created": {"Authorized", "Failed"},
	"Authorized": {"Captured", "Failed"},
	"Captured": {"Refunded", "Partially Refunded", "Chargeback"},
	"Partially Refunded": {"Refunded", "Chargeback"},
	"Failed": set(),
	"Refunded": set(),
	"Chargeback": set(),
}


class HostingPaymentTransaction(Document):
	def validate(self):
		if self.amount is not None and float(self.amount) <= 0:
			frappe.throw("Payment amount must be positive", frappe.ValidationError)
		if self.is_new():
			if self.status not in ("Created", "Authorized", "Captured"):
				frappe.throw("New payments must start as Created, Authorized, or Captured", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Payment status cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
