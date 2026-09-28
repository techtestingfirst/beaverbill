import frappe
from frappe.model.document import Document


class HostingPaymentAllocation(Document):
	def validate(self):
		if self.allocated_amount is not None and float(self.allocated_amount) <= 0:
			frappe.throw("Allocated amount must be positive", frappe.ValidationError)
		if self.reversed_against and self.reversed_against == self.name:
			frappe.throw("Allocation cannot reverse itself", frappe.ValidationError)
