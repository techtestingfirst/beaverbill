import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate, date_diff, add_months

from beaverbill.beaverbill import modifications as engine


class HostingServiceModificationRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from beaverbill.beaverbill.doctype.hosting_modification_event.hosting_modification_event import HostingModificationEvent
		from frappe.types import DF

		applied_at: DF.Datetime | None
		credit_transaction: DF.Link | None
		data_loss_acknowledged: DF.Check
		downgrade_warnings: DF.SmallText | None
		effective_date: DF.Date | None
		effective_mode: DF.Literal["Immediate", "Next Cycle"]
		events: DF.Table[HostingModificationEvent]
		failure_reason: DF.SmallText | None
		idempotency_key: DF.Data | None
		invoice: DF.Link | None
		new_product: DF.Link
		new_product_snapshot: DF.LongText | None
		old_amount: DF.Currency | None
		old_billing_cycle: DF.Data | None
		old_product: DF.Link | None
		old_product_snapshot: DF.LongText | None
		proration_amount: DF.Currency
		service: DF.Link | None
		status: DF.Literal["Pending", "Approved", "Applying", "Completed", "Failed", "Compensated", "Rejected"]
		subscription: DF.Link
		usage_snapshot: DF.LongText | None
	# end: auto-generated types

	def validate(self):
		if self.status == "Pending" and not self.proration_amount:
			self.calculate_proration()
		if self.is_new() and not self.old_product_snapshot:
			engine.freeze_snapshots(self)

	def calculate_proration(self):
		sub = frappe.get_doc("Hosting Subscription", self.subscription)
		new_prod = frappe.get_doc("Hosting Product", self.new_product)

		# Calculate remaining days in current cycle
		renewal_date = getdate(sub.next_renewal_date)
		current_date = getdate(today())

		if renewal_date <= current_date:
			# Already due or past due, no proration credit
			self.proration_amount = float(new_prod.price)
			return

		# Determine total days in current cycle
		months_to_subtract = 1
		if sub.billing_cycle == "Quarterly":
			months_to_subtract = 3
		elif sub.billing_cycle == "Semi-Annually":
			months_to_subtract = 6
		elif sub.billing_cycle == "Annually":
			months_to_subtract = 12

		start_date = add_months(renewal_date, -months_to_subtract)
		total_days = date_diff(renewal_date, start_date) or 30
		remaining_days = date_diff(renewal_date, current_date)

		ratio = float(remaining_days) / float(total_days)

		unused_credit = float(sub.amount) * ratio
		new_cost = float(new_prod.price) * ratio

		self.proration_amount = round(new_cost - unused_credit, 2)

	def process_modification(self):
		"""
		Applies the upgrade/downgrade.
		If proration_amount > 0, creates an invoice.
		If proration_amount <= 0, creates a credit note and immediately completes.
		"""
		if self.status != "Pending":
			return

		sub = frappe.get_doc("Hosting Subscription", self.subscription)

		if self.proration_amount > 0:
			# Upgrade: Create Invoice
			invoice = frappe.get_doc({
				"doctype": "Hosting Invoice",
				"customer": sub.customer,
				"invoice_date": today(),
				"due_date": today(),
				"status": "Unpaid",
				"total_amount": self.proration_amount,
				"currency": sub.currency
			}).insert()
			self.invoice = invoice.name
			self.status = "Approved"
		else:
			# Downgrade: Create Credit Note (Customer Credit Transaction)
			credit_amount = abs(self.proration_amount)
			if credit_amount > 0:
				credit_tx = frappe.get_doc({
					"doctype": "Customer Credit Transaction",
					"customer": sub.customer,
					"transaction_date": today(),
					"amount": credit_amount,
					"type": "Credit",
					"description": f"Prorated credit for downgrade of subscription {sub.name}"
				}).insert()
				self.credit_transaction = credit_tx.name

			# Apply changes immediately
			self.apply_subscription_change()
			self.status = "Completed"

		self.save()

	def apply_subscription_change(self):
		sub = frappe.get_doc("Hosting Subscription", self.subscription)
		new_prod = frappe.get_doc("Hosting Product", self.new_product)
		sub.product = self.new_product
		sub.amount = new_prod.price
		sub.billing_cycle = new_prod.billing_cycle
		sub.save()

		# Trigger simulated provisioning hook
		self.trigger_provisioning_resize(sub)

	def trigger_provisioning_resize(self, subscription):
		if getattr(self, "service", None):
			engine.resize_service_resources(self.service, self.new_product)
			return
		# Simulated provisioning hook
		frappe.logger().info(f"Provisioning: Resized subscription {subscription.name} to product {subscription.product}")


def apply_due_modifications(as_of=None):
	"""Backward-compatible scheduler entry point; delegates to the Phase 7 engine."""
	from beaverbill.beaverbill import modification_apply

	return modification_apply.apply_due_modifications(as_of=as_of)
