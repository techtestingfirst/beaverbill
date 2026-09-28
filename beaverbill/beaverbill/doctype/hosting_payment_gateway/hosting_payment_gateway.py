import frappe
from frappe.model.document import Document


class HostingPaymentGateway(Document):
	def validate(self):
		if self.max_retries is not None and int(self.max_retries) < 0:
			frappe.throw("Max retries cannot be negative", frappe.ValidationError)
		if self.retry_backoff_minutes is not None and int(self.retry_backoff_minutes) < 0:
			frappe.throw("Retry backoff cannot be negative", frappe.ValidationError)

	def currencies(self):
		raw = self.supported_currencies or self.default_currency or "USD"
		return [c.strip().upper() for c in raw.split(",") if c.strip()]
