import frappe
from frappe.model.document import Document

class HostingInvoice(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		currency: DF.Link | None
		customer: DF.Link
		due_date: DF.Date
		invoice_date: DF.Date
		order: DF.Link | None
		status: DF.Literal["Unpaid", "Paid", "Overdue", "Cancelled"]
		total_amount: DF.Currency
	# end: auto-generated types

	pass
