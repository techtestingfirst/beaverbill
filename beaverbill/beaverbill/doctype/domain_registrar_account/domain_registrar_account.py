import frappe
from frappe.model.document import Document


class DomainRegistrarAccount(Document):
	def validate(self):
		if self.credential_reference and any(
			secret in self.credential_reference.lower() for secret in ("key=", "secret=", "password=")
		):
			frappe.throw("Store credentials in the secret vault; keep only a reference here", frappe.ValidationError)
