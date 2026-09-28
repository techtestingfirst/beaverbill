import frappe
from frappe.model.document import Document


class ProviderRequestLog(Document):
	def validate(self):
		# Request logs are append-only audit records; never mutate payloads.
		if not self.is_new():
			previous = self.get_db_value("request_hash")
			if previous and self.request_hash and previous != self.request_hash:
				frappe.throw("Provider Request Log entries are immutable", frappe.ValidationError)
