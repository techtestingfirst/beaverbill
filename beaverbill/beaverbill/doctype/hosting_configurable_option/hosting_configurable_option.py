import frappe
from frappe.model.document import Document

class HostingConfigurableOption(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		option_name: DF.Data
		option_type: DF.Literal["Select", "Checkbox", "Quantity"]
		price_per_unit: DF.Currency
		product: DF.Link
	# end: auto-generated types

	pass
