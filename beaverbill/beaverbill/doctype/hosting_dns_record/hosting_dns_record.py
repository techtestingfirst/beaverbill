import frappe
from frappe.model.document import Document


class HostingDNSRecord(Document):
	def validate(self):
		if self.record_type in ("MX", "SRV") and not int(self.priority or 0):
			frappe.throw(f"{self.record_type} records require a Priority", frappe.ValidationError)
		if self.record_type == "CNAME" and (self.host or "@") in ("@", self.domain):
			frappe.throw("CNAME cannot sit on the zone apex", frappe.ValidationError)
		if int(self.ttl or 0) < 60:
			frappe.throw("TTL must be at least 60 seconds", frappe.ValidationError)
