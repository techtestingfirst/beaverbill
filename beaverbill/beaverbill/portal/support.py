"""Phase 10 portal: Helpdesk ticket bridge and customer notifications.

Tickets ride on frappe/helpdesk HD Tickets through the Phase 12
sync engine: customers and contacts are mirrored, statuses and
priorities resolved, and links recorded as Ticket References.
"""

import frappe

from beaverbill.beaverbill import helpdesk_sync as bridge
from beaverbill.beaverbill.portal.guard import is_staff, portal_customer, portal_endpoint


def _own_ticket(name: str, user=None) -> str:
	"""Return the ticket's raiser after an ownership check (role independent)."""
	user = user or frappe.session.user
	raised_by = frappe.db.get_value("HD Ticket", name, "raised_by")
	if raised_by is None:
		frappe.throw(f"HD Ticket {name} not found", frappe.DoesNotExistError)
	if not is_staff(user) and raised_by != user:
		frappe.throw(f"Ticket {name} does not belong to this customer", frappe.PermissionError)
	return raised_by


@frappe.whitelist()
@portal_endpoint("portal.create_ticket", limit=20)
def create_ticket(subject: str, description: str, service: str | None = None,
				 order: str | None = None, invoice: str | None = None,
				 domain: str | None = None, priority: str | None = None,
				 team: str | None = None, attachments: str | None = None,
				 idempotency_key: str | None = None) -> dict:
	"""Open a support ticket as the caller, linked to owned records."""
	import json as _json

	bridge.require_helpdesk()
	user = frappe.session.user
	portal_customer()
	files = _json.loads(attachments) if attachments else []
	return bridge.create_portal_ticket(
		subject, description, service=service, order=order, invoice=invoice,
		domain=domain, priority=priority, team=team, attachments=files,
		idempotency_key=idempotency_key, user=user,
	)


@frappe.whitelist()
@portal_endpoint("portal.my_tickets", limit=60)
def my_tickets() -> dict:
	"""Tickets raised by the caller, with portal-facing statuses."""
	user = frappe.session.user
	portal_customer()
	rows = frappe.get_all(
		"HD Ticket",
		filters={"raised_by": user},
		fields=["name", "subject", "status", "priority", "creation", "modified"],
		order_by="modified desc",
		ignore_permissions=True,
	)
	for row in rows:
		row["portal_status"] = bridge.portal_status(row.status)
	return {"tickets": rows}


@frappe.whitelist()
@portal_endpoint("portal.ticket_detail", limit=60)
def ticket_detail(ticket: str) -> dict:
	"""Ticket detail: links, SLA, and the caller-visible conversation."""
	user = frappe.session.user
	_own_ticket(ticket, user)
	header = frappe.db.get_value(
		"HD Ticket", ticket,
		["name", "subject", "status", "priority", "description", "agent_group"],
		as_dict=True,
	)
	comments = bridge.visible_comments(ticket, user)
	links = bridge.ticket_links(ticket)
	try:
		sla = bridge.ticket_sla(ticket)
	except (frappe.DoesNotExistError, frappe.PermissionError):
		sla = {}
	return {"ticket": header.name, "subject": header.subject, "status": header.status,
			"portal_status": bridge.portal_status(header.status),
			"priority": header.priority, "description": header.description,
			"team": header.agent_group, "links": links, "sla": sla,
			"comments": comments}


@frappe.whitelist()
@portal_endpoint("portal.ticket_reply", limit=30)
def ticket_reply(ticket: str, message: str) -> dict:
	"""Customer follow-up on their own ticket.

	Replies are Frappe Comments: always customer-visible and never
	mistaken for internal agent notes (see visible_comments).
	"""
	user = frappe.session.user
	_own_ticket(ticket, user)
	if not message or not message.strip():
		frappe.throw("Message is required", frappe.ValidationError)
	reply = frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "HD Ticket",
			"reference_name": ticket,
			"content": message[:2000],
		}
	).insert(ignore_permissions=True)
	return {"ticket": ticket, "reply": reply.name}


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
