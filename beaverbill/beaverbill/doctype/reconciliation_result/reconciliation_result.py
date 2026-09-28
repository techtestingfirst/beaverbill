import frappe
from frappe.model.document import Document

VERDICTS = ("Matched", "Mismatched", "Orphaned Local", "Orphaned Remote", "Unknown")


class ReconciliationResult(Document):
	def validate(self):
		if self.verdict not in VERDICTS:
			frappe.throw(f"Unknown reconciliation verdict: {self.verdict}", frappe.ValidationError)
