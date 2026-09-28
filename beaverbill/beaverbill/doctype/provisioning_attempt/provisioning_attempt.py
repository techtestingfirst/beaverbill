import frappe
from frappe.model.document import Document


class ProvisioningAttempt(Document):
	def validate(self):
		if self.operation and self.attempt_no:
			existing = frappe.db.get_value(
				"Provisioning Attempt",
				{"operation": self.operation, "attempt_no": self.attempt_no, "name": ("!=", self.name or "")},
				"name",
			)
			if existing:
				frappe.throw(
					f"Attempt {self.attempt_no} already recorded for operation {self.operation}",
					frappe.ValidationError,
				)
