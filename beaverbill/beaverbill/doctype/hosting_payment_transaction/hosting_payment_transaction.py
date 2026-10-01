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

	def on_payment_authorized(self, status):
		"""Called by frappe/payments checkout after the provider confirms payment.

		Walks Created -> Authorized -> Captured, then allocates to the source
		invoice. Runs elevated: the payer's session owns no allocation rights,
		and every amount here comes from the server-side invoice, never the client.
		"""
		if status not in ("Authorized", "Completed", "Verified"):
			return None
		self.reload()
		for step in ("Authorized", "Captured"):
			if self.status == step:
				continue
			if self.status == "Created" and step == "Authorized":
				self.status = step
				self.save()
			elif self.status == "Authorized" and step == "Captured":
				self.status = step
				self.save()
		if self.status == "Captured" and self.source_invoice:
			from beaverbill.beaverbill import billing

			try:
				billing.allocate_payment(
					self.name, self.source_invoice, idempotency_key=f"checkout-alloc-{self.name}",
					ignore_permissions=True,
				)
			except frappe.ValidationError:
				pass  # already allocated or nothing outstanding (e.g. webhook won the race)
		return None
