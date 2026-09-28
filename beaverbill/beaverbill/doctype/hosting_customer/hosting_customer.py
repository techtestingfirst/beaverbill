import frappe
from frappe.model.document import Document


class HostingCustomer(Document):
	def validate(self):
		if self.customer_type == "Company" and not self.company_name:
			frappe.throw("Company customers need a company name", frappe.ValidationError)
		if self.customer_type == "Company" and not self.customer_name:
			self.customer_name = self.company_name
		if self.primary_user and not frappe.db.exists("User", self.primary_user):
			frappe.throw(f"Primary user {self.primary_user} does not exist", frappe.ValidationError)
		if self.consent_terms and not self.consent_datetime:
			self.consent_datetime = frappe.utils.now_datetime()
