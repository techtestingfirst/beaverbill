import frappe
from frappe.model.document import Document


class CustomerCreditTransaction(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		balance_after: DF.Currency | None
		currency: DF.Link | None
		customer: DF.Link
		description: DF.Text | None
		hosting_customer: DF.Link | None
		idempotency_key: DF.Data | None
		reversal_of: DF.Link | None
		source_name: DF.Data | None
		source_type: DF.Data | None
		transaction_date: DF.Date
		type: DF.Literal["Credit", "Debit"]
	# end: auto-generated types

	def validate(self):
		if float(self.amount or 0) == 0:
			frappe.throw("Credit amount cannot be zero", frappe.ValidationError)
		if self.reversal_of and self.reversal_of == self.name:
			frappe.throw("Entry cannot reverse itself", frappe.ValidationError)
