import frappe
from frappe.model.document import Document

ALLOWED_TRANSITIONS = {
	"Draft": {"Issued", "Cancelled", "Unpaid"},
	"Issued": {"Partially Paid", "Paid", "Overdue", "Cancelled", "Written Off"},
	"Partially Paid": {"Paid", "Overdue", "Cancelled", "Written Off"},
	"Unpaid": {"Paid", "Partially Paid", "Overdue", "Cancelled", "Written Off"},
	"Paid": set(),
	"Overdue": {"Partially Paid", "Paid", "Written Off", "Cancelled"},
	"Cancelled": set(),
	"Written Off": set(),
}

LEGACY_STATUS_MAP = {"Unpaid": "Issued"}


class HostingInvoice(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from beaverbill.beaverbill.doctype.hosting_invoice_item.hosting_invoice_item import HostingInvoiceItem
		from frappe.types import DF

		cancellation_reason: DF.SmallText | None
		currency: DF.Link | None
		customer: DF.Link
		discount_amount: DF.Currency | None
		due_date: DF.Date
		hosting_customer: DF.Link | None
		idempotency_key: DF.Data | None
		invoice_date: DF.Date
		invoice_pdf: DF.Attach | None
		items: DF.Table[HostingInvoiceItem]
		order: DF.Link | None
		outstanding_amount: DF.Currency | None
		paid_amount: DF.Currency | None
		pricing_snapshot: DF.LongText | None
		reversal_of: DF.Link | None
		reversal_reason: DF.SmallText | None
		source_name: DF.Data | None
		source_type: DF.Data | None
		status: DF.Literal["Draft", "Issued", "Partially Paid", "Paid", "Overdue", "Cancelled", "Written Off", "Unpaid"]
		subtotal: DF.Currency | None
		tax_amount: DF.Currency | None
		total_amount: DF.Currency
	# end: auto-generated types

	def before_validate(self):
		if self.total_amount is not None and self.paid_amount is not None:
			self.outstanding_amount = float(self.total_amount or 0) - float(self.paid_amount or 0)

	def validate(self):
		if float(self.total_amount or 0) < 0:
			frappe.throw("Invoice total cannot be negative", frappe.ValidationError)
		if self.is_new():
			return
		previous = self.get_db_value("status")
		if previous and previous != self.status:
			if self.status == "Cancelled" and not self.cancellation_reason and not self.reversal_reason:
				frappe.throw("Cancellation needs a reason", frappe.ValidationError)
			if self.status not in ALLOWED_TRANSITIONS.get(previous, set()):
				frappe.throw(
					f"Invoice status cannot move from {previous} to {self.status}",
					frappe.ValidationError,
				)

	def on_update(self):
		# Lines stay frozen through the status machine: Paid, Cancelled,
		# and Written Off have no outgoing transitions, so snapshots persist.
		return
