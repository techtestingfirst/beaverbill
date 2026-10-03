import frappe
from frappe.model.document import Document


class HostingOrderForm(Document):
    def validate(self):
        if self.require_tos and not (self.tos_text or "").strip():
            frappe.throw("TOS text is required when TOS is required", frappe.ValidationError)
