import frappe
from frappe.model.document import Document


class HostingModificationEvent(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action: DF.Literal["Created", "Snapshots Frozen", "Proration Calculated", "Approved", "Apply Started", "Resize Succeeded", "Resize Failed", "Rolled Back", "Compensated", "Completed", "Rejected"]
		actor: DF.Data | None
		detail: DF.SmallText | None
		timestamp: DF.Datetime
	# end: auto-generated types

	pass
