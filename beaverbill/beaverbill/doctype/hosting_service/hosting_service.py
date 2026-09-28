import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Pending": {"Provisioning", "Cancellation Pending"},
	"Provisioning": {"Active", "Terminated"},
	"Active": {"Modification Pending", "Suspended", "Cancellation Pending"},
	"Modification Pending": {"Active", "Suspended"},
	"Suspended": {"Active", "Cancellation Pending", "Terminated"},
	"Cancellation Pending": {"Terminated", "Active"},
	"Terminated": {"Archived"},
	"Archived": set(),
}

STATUS_TIMESTAMPS = {
	"Provisioning": "provisioned_at",
	"Suspended": "suspended_at",
	"Cancellation Pending": "cancellation_requested_at",
	"Terminated": "terminated_at",
}

STAFF_ROLES = {"System Manager", "Hosting Admin", "Hosting Support"}


class HostingService(Document):
	def validate(self):
		if self.is_new():
			if self.status != "Pending":
				frappe.throw("New services must start as Pending", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Service status cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
			stamp_field = STATUS_TIMESTAMPS.get(self.status)
			if stamp_field and not self.get(stamp_field):
				self.set(stamp_field, frappe.utils.now_datetime())
