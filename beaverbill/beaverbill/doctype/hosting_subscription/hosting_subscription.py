import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate, add_months

from beaverbill.beaverbill import subscriptions as engine


class HostingSubscription(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		billing_cycle: DF.Literal["Monthly", "Quarterly", "Semi-Annually", "Annually", "Biennially", "Triennially"]
		billing_timezone: DF.Data | None
		cancel_at_period_end: DF.Check
		cancellation_effective_at: DF.Date | None
		cancellation_mode: DF.Literal["", "Immediate", "End of Period"]
		cancellation_requested_at: DF.Datetime | None
		currency: DF.Link | None
		current_period_end: DF.Date | None
		current_period_start: DF.Date | None
		customer: DF.Link
		data_purge_scheduled_at: DF.Date | None
		grace_period_days: DF.Int
		last_error: DF.SmallText | None
		last_invoice: DF.Link | None
		last_retry_at: DF.Datetime | None
		locked_at: DF.Datetime | None
		locked_by: DF.Data | None
		max_retries: DF.Int
		next_renewal_date: DF.Date
		next_retry_at: DF.Datetime | None
		order: DF.Link | None
		product: DF.Link
		reinstatement_count: DF.Int
		renewal_lead_days: DF.Int
		retry_backoff_minutes: DF.Int
		retry_count: DF.Int
		status: DF.Literal["Trial", "Active", "Renewal Pending", "Payment Failed", "Grace Period", "Suspended", "Cancellation Pending", "Terminated", "Archived"]
		suspend_reason: DF.SmallText | None
		terminated_at: DF.Datetime | None
		termination_scheduled_at: DF.Date | None
		trial_end_date: DF.Date | None
	# end: auto-generated types

	def validate(self):
		if self.is_new():
			if self.status not in ("Trial", "Active"):
				frappe.throw("New subscriptions must start as Trial or Active", frappe.ValidationError)
			if not self.next_renewal_date:
				frappe.throw("Next Renewal Date is required", frappe.ValidationError)
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			engine.validate_transition(previous, self.status)
			if self.status == "Terminated" and not self.terminated_at:
				self.terminated_at = frappe.utils.now_datetime()
			if self.status == "Cancellation Pending" and not self.cancellation_requested_at:
				self.cancellation_requested_at = frappe.utils.now_datetime()


def process_subscription_renewals(as_of=None):
	"""Backward-compatible entry point; delegates to the Phase 6 engine."""
	return engine.process_subscription_renewals(as_of=as_of)


def get_customer_wallet_balance(customer):
	txs = frappe.get_all("Customer Credit Transaction", filters={"customer": customer}, fields=["amount"])
	return sum(float(tx.amount) for tx in txs)
