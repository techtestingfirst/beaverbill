import frappe
from frappe.model.document import Document


class HostingPaymentMethod(Document):
	def validate(self):
		if self.last4 and (len(str(self.last4)) != 4 or not str(self.last4).isdigit()):
			frappe.throw("Last 4 must be 4 digits", frappe.ValidationError)
		if self.exp_month is not None and self.exp_month != "":
			month = int(self.exp_month)
			if month < 1 or month > 12:
				frappe.throw("Expiry month must be 1-12", frappe.ValidationError)
