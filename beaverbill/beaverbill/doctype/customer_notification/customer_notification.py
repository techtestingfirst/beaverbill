import frappe
from frappe.model.document import Document


class CustomerNotification(Document):
	def validate(self):
		if not self.created_at:
			self.created_at = frappe.utils.now_datetime()
