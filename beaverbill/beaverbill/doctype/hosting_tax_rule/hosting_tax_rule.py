import frappe
from frappe.model.document import Document


class HostingTaxRule(Document):
	def validate(self):
		if self.rate is not None and not 0 <= float(self.rate) <= 100:
			frappe.throw("Tax rate must be between 0 and 100", frappe.ValidationError)
		if self.effective_to and self.effective_from and self.effective_to < self.effective_from:
			frappe.throw("Effective To cannot be before Effective From", frappe.ValidationError)
