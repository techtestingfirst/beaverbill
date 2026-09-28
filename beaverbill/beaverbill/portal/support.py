"""Phase 10 portal: Helpdesk ticket bridge and customer notifications.

Tickets ride on frappe/helpdesk HD Tickets with raised_by set to the
caller and via_customer_portal flagged. Phase 12 owns the full
customer/contact synchronization; here we bridge the minimum the
portal needs without coupling Beaver Bill to helpdesk internals.
"""

import frappe

from beaverbill.beaverbill.portal.guard import is_staff, portal_customer, portal_endpoint


def _require_helpdesk() -> None:
	if not frappe.db.exists("DocType", "HD Ticket"):
		frappe.throw("Helpdesk is not configured on this site", frappe.ValidationError)


def _default_status() -> str:
	name = frappe.db.get_value("HD Ticket Status", {"name": ("like", "Open%")}, "name")
	if name:
		return name
	first = frappe.get_all("HD Ticket Status", pluck="name", limit=1, ignore_permissions=True)
	if not first:
		frappe.throw("No HD Ticket Status configured", frappe.ValidationError)
	return first[0]


def _own_ticket(name: str, user=None) -> dict:
	"""Ownership-checked ticket header via the DB layer (role independent).

	Beaver Bill does not take a dependency on helpdesk roles; the
	portal filters by raised_by and Phase 12 formalizes the sync.
	"""
	user = user or frappe.session.user
	header = frappe.db.get_value(
		"HD Ticket", name, ["name", "subject", "status", "priority", "description", "raised_by"],
		as_dict=True,
	)
	if not header:
		frappe.throw(f"HD Ticket {name} not found", frappe.DoesNotExistError)
	if not is_staff(user) and header.raised_by != user:
		frappe.throw(f"Ticket {name} does not belong to this customer", frappe.PermissionError)
	return header


def _check_attachments(attachments: list, user: str) -> None:
	"""Every attachment URL must be an existing File owned by the caller."""
	for url in attachments or []:
		row = frappe.db.get_value("File", {"file_url": url}, ["name", "owner"])
		if not row:
			frappe.throw(f"Attachment not found: {url}", frappe.ValidationError)
		if row[1] != user:
			frappe.throw(f"Attachment does not belong to this customer: {url}", frappe.PermissionError)


@frappe.whitelist()
@portal_endpoint("portal.create_ticket", limit=20)
def create_ticket(subject: str, description: str, service: str | None = None,
				 priority: str | None = None, attachments: str | None = None) -> dict:
	"""Open a support ticket as the caller, optionally linked to a service."""
	import json as _json

	_require_helpdesk()
	user = frappe.session.user
	portal_customer()
	footer = ""
	if service:
		from beaverbill.beaverbill.portal.guard import own_service_or_throw

		svc = own_service_or_throw(service, user)
		footer = f"\n\nLinked service: {svc.name} ({svc.product}, {svc.status})"
	files = _json.loads(attachments) if attachments else []
	_check_attachments(files, user)
	# Helpdesk controllers (tags, SLA, communications) assume agent-side
	# permissions. Attribution stays exact via raised_by; Phase 12 replaces
	# this bridge with the HD Customer role and record sync.
	previous_user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		doc = frappe.get_doc(
			{
				"doctype": "HD Ticket",
				"subject": subject[:200],
				"description": (description or "") + footer,
				"raised_by": user,
				"status": _default_status(),
				"via_customer_portal": 1,
			}
		)
		if priority and frappe.db.exists("HD Ticket Priority", priority):
			doc.priority = priority
		doc.insert(ignore_permissions=True)
	finally:
		frappe.set_user(previous_user)
	if files:
		frappe.db.set_value("HD Ticket", doc.name, "description",
							(doc.description or "") + f"\nAttachments: {', '.join(files)}")
	return {"ticket": doc.name, "status": doc.status}


@frappe.whitelist()
@portal_endpoint("portal.my_tickets", limit=60)
def my_tickets() -> dict:
	"""Tickets raised by the caller."""
	user = frappe.session.user
	portal_customer()
	rows = frappe.get_all(
		"HD Ticket",
		filters={"raised_by": user},
		fields=["name", "subject", "status", "priority", "creation", "modified"],
		order_by="modified desc",
		ignore_permissions=True,
	)
	return {"tickets": rows}


@frappe.whitelist()
@portal_endpoint("portal.ticket_detail", limit=60)
def ticket_detail(ticket: str) -> dict:
	"""Ticket detail plus visible comments (ownership enforced)."""
	header = _own_ticket(ticket)
	comments = frappe.get_all(
		"HD Ticket Comment",
		filters={"reference_ticket": header.name},
		fields=["name", "content", "commented_by", "creation"],
		order_by="creation asc",
		ignore_permissions=True,
	)
	legacy = frappe.get_all(
		"Comment",
		filters={"reference_doctype": "HD Ticket", "reference_name": header.name},
		fields=["name", "content", "owner", "creation"],
		order_by="creation asc",
		ignore_permissions=True,
	)
	return {"ticket": header.name, "subject": header.subject, "status": header.status,
			"priority": header.priority, "description": header.description,
			"comments": comments + legacy}


@frappe.whitelist()
@portal_endpoint("portal.ticket_reply", limit=30)
def ticket_reply(ticket: str, message: str) -> dict:
	"""Customer follow-up on their own ticket."""
	user = frappe.session.user
	header = _own_ticket(ticket, user)
	if not message or not message.strip():
		frappe.throw("Message is required", frappe.ValidationError)
	reply = frappe.get_doc(
		{
			"doctype": "HD Ticket Comment",
			"reference_ticket": header.name,
			"content": message[:2000],
			"commented_by": user,
		}
	).insert(ignore_permissions=True)
	return {"ticket": header.name, "reply": reply.name}


@frappe.whitelist()
@portal_endpoint("portal.list_notifications", limit=60)
def list_notifications(unread_only: bool = False) -> dict:
	"""Customer notification feed for the caller."""
	customer = portal_customer()
	filters = {"customer": customer}
	if unread_only:
		filters["read"] = 0
	rows = frappe.get_all(
		"Customer Notification",
		filters=filters,
		fields=["name", "subject", "message", "read", "created_at"],
		order_by="creation desc",
		limit_page_length=50,
	)
	return {"notifications": rows}


@frappe.whitelist()
@portal_endpoint("portal.unread_count", limit=60)
def unread_count() -> dict:
	"""Count of unread notifications."""
	customer = portal_customer()
	count = frappe.db.count("Customer Notification", {"customer": customer, "read": 0})
	return {"unread": count}


@frappe.whitelist()
@portal_endpoint("portal.mark_read", limit=60)
def mark_read(name: str) -> dict:
	"""Mark the caller's notification as read."""
	customer = portal_customer()
	doc = frappe.get_doc("Customer Notification", name)
	if doc.customer != customer and not is_staff():
		frappe.throw(f"Notification {name} does not belong to this customer", frappe.PermissionError)
	doc.read = 1
	doc.save()
	return {"notification": doc.name, "read": 1}
