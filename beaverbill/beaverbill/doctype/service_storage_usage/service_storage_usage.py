import frappe
from frappe.model.document import Document


class ServiceStorageUsage(Document):
	def validate(self):
		overage = max(float(self.used_gb or 0) - float(self.quota_gb or 0), 0)
		self.overage_gb = round(overage, 3)
		if not self.measured_at:
			self.measured_at = frappe.utils.now_datetime()
		if self.service and not self.customer:
			self.customer = frappe.db.get_value("Hosting Service", self.service, "customer")
