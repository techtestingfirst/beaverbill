import frappe
from frappe.model.document import Document


class ScopedAPIToken(Document):
	def validate(self):
		if not self.token_hash:
			frappe.throw("Token hash is required", frappe.ValidationError)
		if self.expires_at and self.last_used_at and str(self.last_used_at) < "2000-01-01":
			frappe.throw("Last-used timestamp looks invalid", frappe.ValidationError)
