import frappe
from frappe.model.document import Document

class DatacenterAsset(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		asset_name: DF.Data
		asset_type: DF.Literal["Rack", "PDU", "Switch", "Patch Panel", "UPS"]
		rack_location: DF.Data | None
		status: DF.Literal["Active", "Spare", "Faulty"]
		u_position: DF.Int
	# end: auto-generated types

	pass
