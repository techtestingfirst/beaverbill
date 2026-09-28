import frappe
from frappe.model.document import Document


class SecurityAuditLog(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw("Security Audit Log rows are immutable", frappe.ValidationError)
		if not self.at:
			self.at = frappe.utils.now_datetime()
