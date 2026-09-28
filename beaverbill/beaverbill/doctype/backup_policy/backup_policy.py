import frappe
from frappe.model.document import Document


class BackupPolicy(Document):
	def validate(self):
		if int(self.retention_count or 0) < 1:
			frappe.throw("Retention Count must be at least 1", frappe.ValidationError)
		if int(self.retention_days or 0) < 1:
			frappe.throw("Retention Days must be at least 1", frappe.ValidationError)
		if self.service and not self.customer:
			self.customer = frappe.db.get_value("Hosting Service", self.service, "customer")
