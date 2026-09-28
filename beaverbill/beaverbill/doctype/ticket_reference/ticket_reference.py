from frappe.model.document import Document


class TicketReference(Document):
	"""Links an HD Ticket (stored by name; helpdesk stays optional) to
	Beaver Bill records. Uniqueness on `ticket` keeps links idempotent."""

	pass
