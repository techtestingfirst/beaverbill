import frappe
from frappe.model.document import Document
from frappe.utils import today, add_months

ALLOWED_TRANSITIONS = {
	"Draft": {"Confirmed", "Cancelled", "Pending"},
	"Confirmed": {"Payment Pending", "Pending", "Cancelled"},
	"Payment Pending": {"Paid", "Cancelled"},
	"Pending": {"Paid", "Cancelled", "Confirmed", "Payment Pending"},
	"Paid": {"Processing", "Cancelled"},
	"Processing": {"Completed", "Cancelled"},
	"Completed": set(),
	"Cancelled": set(),
}


class HostingOrder(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from beaverbill.beaverbill.doctype.hosting_order_item.hosting_order_item import HostingOrderItem
		from frappe.types import DF

		cancellation_reason: DF.SmallText | None
		currency: DF.Link | None
		customer: DF.Link
		hosting_customer: DF.Link | None
		idempotency_key: DF.Data | None
		items: DF.Table[HostingOrderItem]
		order_date: DF.Date
		promo_code: DF.Link | None
		status: DF.Literal["Draft", "Confirmed", "Payment Pending", "Pending", "Paid", "Processing", "Completed", "Cancelled"]
		total_amount: DF.Currency
	# end: auto-generated types

	def validate(self):
		if self.is_new():
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status == "Cancelled" and not self.cancellation_reason:
				pass
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Order status cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)

	def on_submit(self):
		pass

	def process_payment(self):
		"""
		Simulates payment processing. Marks order as Paid, creates a paid Hosting Invoice,
		and provisions active Hosting Subscriptions for each item.

		Phase 4 keeps this signature and result. The invoice now carries
		line snapshots and a paid/outstanding ledger via billing helpers.
		"""
		if self.status == "Paid":
			return

		self.status = "Paid"
		self.save()

		# Create Invoice
		invoice = frappe.get_doc({
			"doctype": "Hosting Invoice",
			"customer": self.customer,
			"invoice_date": today(),
			"due_date": today(),
			"status": "Paid",
			"total_amount": self.total_amount,
			"paid_amount": self.total_amount,
			"outstanding_amount": 0,
			"currency": self.currency,
			"order": self.name
		}).insert()

		# Create Subscriptions
		for item in self.items:
			product = frappe.get_doc("Hosting Product", item.product)
			months_to_add = 1
			if product.billing_cycle == "Quarterly":
				months_to_add = 3
			elif product.billing_cycle == "Semi-Annually":
				months_to_add = 6
			elif product.billing_cycle == "Annually":
				months_to_add = 12

			frappe.get_doc({
				"doctype": "Hosting Subscription",
				"customer": self.customer,
				"product": item.product,
				"status": "Active",
				"billing_cycle": product.billing_cycle,
				"next_renewal_date": add_months(today(), months_to_add),
				"amount": item.total,
				"currency": self.currency,
				"order": self.name
			}).insert()
