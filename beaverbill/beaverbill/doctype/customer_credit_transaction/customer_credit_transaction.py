import frappe
from frappe.model.document import Document

class CustomerCreditTransaction(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		customer: DF.Link
		description: DF.Text | None
		transaction_date: DF.Date
		type: DF.Literal["Credit", "Debit"]
	# end: auto-generated types

	pass
