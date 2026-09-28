import frappe
from frappe.model.document import Document


class HostingProductPrice(Document):
	def validate(self):
		if self.effective_to and self.effective_from and self.effective_to < self.effective_from:
			frappe.throw("Effective To cannot be before Effective From", frappe.ValidationError)
		if self.price is not None and float(self.price) < 0:
			frappe.throw("Price cannot be negative", frappe.ValidationError)
