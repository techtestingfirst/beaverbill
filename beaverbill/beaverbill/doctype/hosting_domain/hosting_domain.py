import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Pending Registration": {"Active", "Cancelled"},
	"Active": {"Transfer Pending", "Expired", "Cancelled"},
	"Transfer Pending": {"Active", "Expired", "Cancelled"},
	"Expired": {"Grace Period", "Active", "Cancelled"},
	"Grace Period": {"Active", "Redemption", "Cancelled"},
	"Redemption": {"Active", "Terminated"},
	"Cancelled": {"Terminated", "Pending Registration"},
	"Terminated": set(),
}


class HostingDomain(Document):
	def validate(self):
		if self.domain_name:
			self.domain_name = self.domain_name.strip().lower()
		if self.is_new():
			if self.status not in ("Pending Registration", "Active"):
				frappe.throw("New domains must start as Pending Registration or Active", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Domain cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
			if self.status in ("Cancelled", "Terminated") and not self.cancelled_at:
				self.cancelled_at = frappe.utils.now_datetime()


def process_domain_renewals(as_of=None):
	"""Scheduler entry point; delegates to the Phase 9 engine."""
	from beaverbill.beaverbill import domains

	return domains.process_domain_renewals(as_of=as_of)
