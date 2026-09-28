import frappe
from frappe.model.document import Document


class MonitoringAlert(Document):
	def validate(self):
		if not self.first_seen:
			self.first_seen = frappe.utils.now_datetime()
		self.last_seen = frappe.utils.now_datetime()
		if self.status == "Resolved" and not self.resolved_at:
			self.resolved_at = frappe.utils.now_datetime()
