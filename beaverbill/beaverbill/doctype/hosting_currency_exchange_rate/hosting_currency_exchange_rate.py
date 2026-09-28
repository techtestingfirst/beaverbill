import frappe
from frappe.model.document import Document


class HostingCurrencyExchangeRate(Document):
	def validate(self):
		if self.from_currency == self.to_currency:
			frappe.throw("From and To currencies must differ", frappe.ValidationError)
		if self.rate is not None and float(self.rate) <= 0:
			frappe.throw("Exchange rate must be positive", frappe.ValidationError)
