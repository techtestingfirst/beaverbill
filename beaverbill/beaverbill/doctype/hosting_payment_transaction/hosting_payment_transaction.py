import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Created": {"Authorized", "Failed"},
	"Authorized": {"Captured", "Failed"},
	"Captured": {"Refunded", "Partially Refunded", "Chargeback"},
	"Partially Refunded": {"Refunded", "Chargeback"},
	# Phase 5 retry: a failed payment may start a new attempt.
	"Failed": {"Created"},
	"Refunded": set(),
	"Chargeback": set(),
}


class HostingPaymentTransaction(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		currency: DF.Link | None
		customer: DF.Link
		gateway: DF.Data | None
		gateway_event_id: DF.Data | None
		gateway_reference: DF.Data | None
		idempotency_key: DF.Data | None
		last_error: DF.SmallText | None
		next_retry_at: DF.Datetime | None
		payment_date: DF.Date
		payment_token_ref: DF.Data | None
		remarks: DF.SmallText | None
		retry_count: DF.Int | None
		source_invoice: DF.Link | None
		status: DF.Literal["Created", "Authorized", "Captured", "Failed", "Refunded", "Partially Refunded", "Chargeback"]
	# end: auto-generated types

	def validate(self):
		if self.amount is not None and float(self.amount) <= 0:
			frappe.throw("Payment amount must be positive", frappe.ValidationError)
		if self.is_new():
			if self.status not in ("Created", "Authorized", "Captured"):
				frappe.throw("New payments must start as Created, Authorized, or Captured", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Payment status cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)
