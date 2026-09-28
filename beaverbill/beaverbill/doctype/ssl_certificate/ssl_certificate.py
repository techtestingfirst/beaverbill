import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Pending Validation": {"Active", "Failed", "Cancelled"},
	"Active": {"Renewal Pending", "Expired", "Failed", "Revoked", "Cancelled"},
	"Renewal Pending": {"Active", "Expired", "Failed"},
	"Expired": {"Renewal Pending", "Cancelled"},
	"Failed": {"Pending Validation", "Active", "Cancelled"},
	"Revoked": set(),
	"Cancelled": set(),
}


class SSLCertificate(Document):
	def validate(self):
		if self.is_new():
			if self.status not in ("Pending Validation", "Active"):
				frappe.throw("New certificates must start as Pending Validation or Active", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Certificate cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)


def monitor_certificates(as_of=None):
	"""Scheduler entry point; delegates to the Phase 9 engine."""
	from beaverbill.beaverbill import certificates

	return certificates.monitor_certificates(as_of=as_of)
