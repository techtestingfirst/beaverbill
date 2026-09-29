"""Phase 12 helpdesk bridge: same-site sync with frappe/helpdesk.

Deployment: same-site. The helpdesk app runs on the same site as
Beaver Bill, so tickets, customers, and statuses are native
documents — no cross-site API, no credential sync, no split-brain
records. Beaver Bill Hosting Customer/Contact rows are the source
of truth; HD Customer/Member rows are synced mirrors keyed through
Helpdesk Sync Log. Nothing in the helpdesk app itself is modified.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from beaverbill.beaverbill import settings as bb_settings
from beaverbill.beaverbill.notifications import notify

SAME_SITE_DEPLOYMENT = True

MAX_ATTEMPTS = 5
BACKOFF_BASE_MINUTES = 5
BACKOFF_CAP_MINUTES = 4 * 60


def _max_attempts() -> int:
	return bb_settings.get_int("sync_max_attempts", MAX_ATTEMPTS)


def _backoff_base() -> int:
	return bb_settings.get_int("sync_backoff_base_minutes", BACKOFF_BASE_MINUTES)


def _backoff_cap() -> int:
	return bb_settings.get_int("sync_backoff_cap_minutes", BACKOFF_CAP_MINUTES)

# Portal-facing display names for HD Ticket Status values.
PORTAL_STATUS_MAP = {
	"Open": "Open",
	"Replied": "In Progress",
	"Resolved": "Resolved",
	"Closed": "Closed",
}

PRIORITY_DEFAULT = "Medium"
STATUS_DEFAULT = "Open"

# Fault injection for tests: {"customer": msg, "contact": msg}
SYNC_FAULTS: dict = {}


def helpdesk_available() -> bool:
	return bool(
		frappe.db.exists("DocType", "HD Ticket") and frappe.db.exists("DocType", "HD Customer")
	)


def require_helpdesk() -> None:
	if not helpdesk_available():
		frappe.throw("Helpdesk is not configured on this site", frappe.ValidationError)


def grant_portal_roles(user: str) -> list:
	"""Portal roles for a login. HD Customer only when helpdesk is present."""
	roles = ["Hosting Customer"]
	if helpdesk_available() and frappe.db.exists("Role", "HD Customer"):
		roles.append("HD Customer")
		doc = frappe.get_doc("User", user)
		doc.add_roles(*roles)
		return roles
	frappe.get_doc("User", user).add_roles("Hosting Customer")
	return ["Hosting Customer"]


def portal_status(hd_status: str | None) -> str:
	"""Display name for an HD status; unknown values pass through."""
	return PORTAL_STATUS_MAP.get(hd_status or "", hd_status or "Open")


def resolve_status(name: str | None) -> str:
	wanted = name or STATUS_DEFAULT
	if frappe.db.exists("HD Ticket Status", wanted):
		return wanted
	fallback = frappe.db.get_value("HD Ticket Status", {"name": ("like", "Open%")}, "name")
	if fallback:
		return fallback
	first = frappe.get_all("HD Ticket Status", pluck="name", limit=1, ignore_permissions=True)
	if not first:
		frappe.throw("No HD Ticket Status configured", frappe.ValidationError)
	return first[0]


def resolve_priority(name: str | None) -> str | None:
	wanted = name or PRIORITY_DEFAULT
	if frappe.db.exists("HD Ticket Priority", wanted):
		return wanted
	return None


def resolve_team(name: str | None) -> str | None:
	if name and frappe.db.exists("HD Team", name):
		return name
	return None


def ticket_sla(ticket: str) -> dict:
	"""Read-only SLA snapshot for a ticket (agents own the policy)."""
	row = frappe.db.get_value(
		"HD Ticket", ticket, ["sla", "response_by", "resolution_by", "agreement_status"], as_dict=True
	)
	if not row:
		frappe.throw(f"HD Ticket {ticket} not found", frappe.DoesNotExistError)
	return {
		"sla": row.sla,
		"response_by": str(row.response_by or ""),
		"resolution_by": str(row.resolution_by or ""),
		"agreement_status": row.agreement_status,
	}


def email_health() -> dict:
	"""Inbound/outbound mail configuration report (admins own the mailboxes)."""
	incoming = frappe.get_all("Email Account", filters={"enable_incoming": 1}, fields=["name", "email_id"], ignore_permissions=True)
	outgoing = frappe.get_all("Email Account", filters={"enable_outgoing": 1}, fields=["name"], ignore_permissions=True)
	default_out = frappe.db.get_value("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, "name")
	return {
		"same_site": SAME_SITE_DEPLOYMENT,
		"inbound_configured": bool(incoming),
		"inbound_accounts": [r.email_id for r in incoming],
		"outbound_configured": bool(outgoing),
		"default_outgoing": default_out,
		"note": "Configure inbound/outbound Email Accounts in site admin; "
		"helpdesk consumes them natively on this site.",
	}


def _backoff(attempts: int) -> int:
	return min(_backoff_base() * (2 ** max(int(attempts or 0), 0)), _backoff_cap())


def _sync_row(entity_type: str, entity: str, key: str) -> object:
	name = frappe.db.get_value("Helpdesk Sync Log", {"idempotency_key": key}, "name")
	if name:
		return frappe.get_doc("Helpdesk Sync Log", name)
	return frappe.get_doc(
		{
			"doctype": "Helpdesk Sync Log",
			"entity_type": entity_type,
			"entity": entity,
			"status": "Pending",
			"attempts": 0,
			"max_attempts": _max_attempts(),
			"idempotency_key": key,
		}
	).insert(ignore_permissions=True)


def _succeed(row: object, hd_name: str) -> object:
	row.status = "Synced"
	row.hd_name = hd_name
	row.error_type = None
	row.last_error = None
	row.next_retry_at = None
	row.save(ignore_permissions=True)
	return row


def _fail(row: object, error: str, error_type: str = "transient") -> object:
	row.attempts = int(row.attempts or 0) + 1
	row.error_type = error_type
	row.last_error = (error or "")[:1000]
	if error_type == "permanent" or int(row.attempts) >= int(row.max_attempts or _max_attempts()):
		row.status = "Failed"
		row.next_retry_at = None
	else:
		row.status = "Pending"
		row.next_retry_at = add_to_date(now_datetime(), minutes=_backoff(row.attempts))
	row.save(ignore_permissions=True)
	return row


def synced_hd_name(entity_type: str, entity: str) -> str | None:
	return frappe.db.get_value(
		"Helpdesk Sync Log",
		{"entity_type": entity_type, "entity": entity, "status": "Synced"},
		"hd_name",
	)


def sync_customer(customer: str, idempotency_key: str | None = None) -> dict:
	"""Mirror a Hosting Customer to HD Customer. Idempotent."""
	require_helpdesk()
	key = idempotency_key or f"customer-{customer}"
	row = _sync_row("Customer", customer, key)
	if row.status == "Synced" and row.hd_name and frappe.db.exists("HD Customer", row.hd_name):
		return {"hd_customer": row.hd_name, "duplicate_request": True}
	if SYNC_FAULTS.get("customer"):
		_fail(row, SYNC_FAULTS["customer"], "transient")
		return {"hd_customer": None, "status": row.status, "error": SYNC_FAULTS["customer"]}
	doc = frappe.get_doc("Hosting Customer", customer)
	email = frappe.db.get_value("User", doc.primary_user, "email") or doc.primary_user
	hd_name = frappe.db.get_value("HD Customer", {"email_id": email}, "name")
	if not hd_name:
		hd_name = frappe.get_doc(
			{
				"doctype": "HD Customer",
				"customer_name": doc.customer_name or doc.name,
				"email_id": email,
			}
		).insert(ignore_permissions=True).name
	_succeed(row, hd_name)
	return {"hd_customer": hd_name, "status": "Synced"}


def sync_contact(contact: str, idempotency_key: str | None = None) -> dict:
	"""Mirror a Hosting Customer Contact to HD Customer members. Idempotent."""
	require_helpdesk()
	key = idempotency_key or f"contact-{contact}"
	row = _sync_row("Contact", contact, key)
	if row.status == "Synced" and row.hd_name and frappe.db.exists("Contact", row.hd_name):
		return {"contact": row.hd_name, "duplicate_request": True}
	if SYNC_FAULTS.get("contact"):
		_fail(row, SYNC_FAULTS["contact"], "transient")
		return {"contact": None, "status": row.status, "error": SYNC_FAULTS["contact"]}
	src = frappe.get_doc("Hosting Customer Contact", contact)
	parent = sync_customer(src.customer)
	core = frappe.db.get_value("Contact", {"email_id": src.email}, "name")
	if not core:
		core = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": (src.full_name or src.email or "?")[:140],
				"email_id": src.email,
				"phone": src.phone,
			}
		).insert(ignore_permissions=True).name
	core_doc = frappe.get_doc("Contact", core)
	linked = any(
		link.link_doctype == "HD Customer" and link.link_name == parent["hd_customer"]
		for link in core_doc.links
	)
	if not linked:
		core_doc.append("links", {"link_doctype": "HD Customer", "link_name": parent["hd_customer"]})
		core_doc.save(ignore_permissions=True)
	hd = frappe.get_doc("HD Customer", parent["hd_customer"])
	if not any(r.contact_name == core for r in hd.contacts):
		hd.append("contacts", {"contact_name": core})
		hd.save(ignore_permissions=True)
	_succeed(row, core)
	return {"contact": core, "status": "Synced"}


def process_due_syncs(limit: int = 50) -> dict:
	"""Scheduler: retry due customer/contact syncs. Ticket rows are
	creation-time dedup markers and are never re-driven."""
	ran = {"synced": 0, "failed": 0, "pending": 0, "skipped": 0}
	now = now_datetime()
	rows = frappe.get_all(
		"Helpdesk Sync Log",
		filters={"status": "Pending"},
		fields=["name", "entity_type", "entity"],
		order_by="creation asc",
		limit_page_length=limit,
	)
	for item in rows:
		row = frappe.get_doc("Helpdesk Sync Log", item.name)
		if row.next_retry_at and row.next_retry_at > now:
			ran["skipped"] += 1
			continue
		try:
			if row.entity_type == "Customer":
				out = sync_customer(row.entity, idempotency_key=row.idempotency_key)
			elif row.entity_type == "Contact":
				out = sync_contact(row.entity, idempotency_key=row.idempotency_key)
			else:
				ran["skipped"] += 1
				continue
			if out.get("status") == "Synced" or out.get("duplicate_request"):
				ran["synced"] += 1
			else:
				ran["failed"] += 1
		except Exception as exc:
			_fail(row, str(exc), "unknown")
			ran["failed"] += 1
		frappe.db.commit()
	ran["pending"] = frappe.db.count("Helpdesk Sync Log", {"status": "Pending"})
	return ran


def sync_failures() -> dict:
	"""Failure report: stuck sync rows for staff triage."""
	rows = frappe.get_all(
		"Helpdesk Sync Log",
		filters={"status": "Failed"},
		fields=["name", "entity_type", "entity", "hd_name", "attempts",
				"error_type", "last_error", "modified"],
		order_by="modified desc",
		limit_page_length=100,
	)
	return {"failures": rows}


def ensure_raiser_contact(user: str, hd_customer: str) -> str | None:
	"""Find-or-create the core Contact for a login and link it to HD Customer.

	Helpdesk auto-attaches the raiser's Contact to new tickets and then
	validates it against the ticket customer, so the link must exist
	before insert.
	"""
	email = frappe.db.get_value("User", user, "email") or user
	if not email or "@" not in email:
		return None
	name = frappe.db.get_value("Contact", {"email_id": email})
	if not name:
		name = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": (frappe.db.get_value("User", user, "first_name") or email.split("@")[0])[:140],
				"email_id": email,
			}
		).insert(ignore_permissions=True).name
	doc = frappe.get_doc("Contact", name)
	changed = False
	if not doc.get("user"):
		doc.user = user
		changed = True
	if not any(
		link.link_doctype == "HD Customer" and link.link_name == hd_customer for link in doc.links
	):
		doc.append("links", {"link_doctype": "HD Customer", "link_name": hd_customer})
		changed = True
	if changed:
		doc.save(ignore_permissions=True)
	# Helpdesk resolves ticket customers through HD Customer members,
	# so the raiser must be a member, not merely linked.
	hd = frappe.get_doc("HD Customer", hd_customer)
	if not any(r.contact_name == name for r in hd.contacts):
		hd.append("contacts", {"contact_name": name})
		hd.save(ignore_permissions=True)
	return name


def link_ticket(ticket: str, customer: str, service: str | None = None,
				order: str | None = None, invoice: str | None = None,
				domain: str | None = None, opened_by: str | None = None) -> object:
	"""Attach Beaver Bill records to a ticket, validating ownership."""
	from beaverbill.beaverbill.portal import guard

	if service:
		guard.own_service_or_throw(service)
	if order:
		doc = frappe.get_doc("Hosting Order", order)
		guard.portal_customer()
		if not guard.may_access_customer(doc.hosting_customer or "") and doc.customer != frappe.session.user:
			frappe.throw(f"Order {order} does not belong to this customer", frappe.PermissionError)
	if invoice:
		guard.own_invoice_or_throw(invoice)
	if domain:
		guard.own_domain_or_throw(domain)
	hit = frappe.db.get_value("Ticket Reference", {"ticket": ticket}, "name")
	if hit:
		return frappe.get_doc("Ticket Reference", hit)
	return frappe.get_doc(
		{
			"doctype": "Ticket Reference",
			"ticket": ticket,
			"customer": customer,
			"service": service,
			"order": order,
			"invoice": invoice,
			"domain": domain,
			"opened_by": opened_by or frappe.session.user,
			"opened_at": now_datetime(),
		}
	).insert(ignore_permissions=True)


def ticket_links(ticket: str) -> dict:
	"""Linked Beaver Bill records for display on a ticket."""
	row = frappe.db.get_value(
		"Ticket Reference", {"ticket": ticket},
		["customer", "service", "order", "invoice", "domain", "opened_by", "opened_at"],
		as_dict=True,
	)
	return dict(row) if row else {}


def visible_comments(ticket: str, user: str | None = None) -> list:
	"""Conversation visible to a portal caller.

	Internal-note rule: agent-authored HD Ticket Comments are
	internal-only and hidden. Shown are (1) Frappe Comments on the
	ticket (portal replies and anything agents share there) and
	(2) HD Ticket Comments authored by the caller. Staff see all.
	"""
	from beaverbill.beaverbill.portal.guard import is_staff

	user = user or frappe.session.user
	staff = is_staff(user)
	comments = frappe.get_all(
		"HD Ticket Comment",
		filters={"reference_ticket": ticket},
		fields=["name", "content", "commented_by", "creation"],
		order_by="creation asc",
		ignore_permissions=True,
	)
	shown = [dict(c, kind="agent-note") for c in comments if staff or c.commented_by == user]
	legacy = frappe.get_all(
		"Comment",
		filters={"reference_doctype": "HD Ticket", "reference_name": ticket},
		fields=["name", "content", "owner", "creation"],
		order_by="creation asc",
		ignore_permissions=True,
	)
	shown.extend(dict(c, kind="reply", commented_by=c.owner) for c in legacy)
	shown.sort(key=lambda c: str(c.get("creation") or ""))
	return shown


def check_attachments(attachments: list, user: str) -> None:
	"""Every attachment URL must be an existing File owned by the caller."""
	for url in attachments or []:
		row = frappe.db.get_value("File", {"file_url": url}, ["name", "owner"])
		if not row:
			frappe.throw(f"Attachment not found: {url}", frappe.ValidationError)
		if row[1] != user:
			frappe.throw(f"Attachment does not belong to this customer: {url}", frappe.PermissionError)


def create_portal_ticket(subject: str, description: str, service: str | None = None, order: str | None = None, invoice: str | None = None, domain: str | None = None, priority: str | None = None, team: str | None = None, attachments: list | None = None, idempotency_key: str | None = None, user: str | None = None) -> dict:
	"""End-to-end portal ticket flow: sync, map, dedup, link."""
	from beaverbill.beaverbill.portal import guard

	require_helpdesk()
	user = user or frappe.session.user
	customer = guard.portal_customer(user)
	if idempotency_key:
		hit = frappe.db.get_value(
			"Helpdesk Sync Log",
			{"entity_type": "Ticket", "idempotency_key": idempotency_key, "status": "Synced"},
			"hd_name",
		)
		if hit:
			return {"ticket": hit, "status": frappe.db.get_value("HD Ticket", hit, "status"),
					"duplicate_request": True}
	check_attachments(attachments or [], user)
	synced = sync_customer(customer)
	raiser_contact = ensure_raiser_contact(user, synced["hd_customer"])
	primary = frappe.db.get_value(
		"Hosting Customer Contact", {"customer": customer, "is_primary": 1}, "name"
	) or frappe.db.get_value("Hosting Customer Contact", {"customer": customer}, "name")
	core_contact = sync_contact(primary)["contact"] if primary else raiser_contact
	footer_lines = []
	for label, value in (("Service", service), ("Order", order), ("Invoice", invoice), ("Domain", domain)):
		if value:
			footer_lines.append(f"{label}: {value}")
	footer = ("\n\nLinked records:\n" + "\n".join(footer_lines)) if footer_lines else ""
	doc = frappe.get_doc(
		{
			"doctype": "HD Ticket",
			"subject": (subject or "")[:200],
			"description": (description or "") + footer,
			"raised_by": user,
			"status": resolve_status(None),
			"priority": resolve_priority(priority),
			"agent_group": resolve_team(team),
			"customer": synced["hd_customer"],
			"contact": core_contact,
			"via_customer_portal": 1,
		}
	)
	doc.insert()
	if attachments:
		frappe.db.set_value("HD Ticket", doc.name, "description",
							(doc.description or "") + f"\nAttachments: {', '.join(attachments)}")
	link_ticket(doc.name, customer, service, order, invoice, domain, opened_by=user)
	if idempotency_key:
		row = _sync_row("Ticket", idempotency_key, idempotency_key)
		_succeed(row, doc.name)
	notify(customer, f"Ticket {doc.name} opened", subject, "HD Ticket", doc.name)
	return {"ticket": doc.name, "status": doc.status}


@frappe.whitelist()
def retry_sync(name: str) -> dict:
	"""Staff action: requeue a Failed sync row for the next scheduler run."""
	from beaverbill.beaverbill.portal.guard import is_staff

	if not is_staff():
		frappe.throw("Only staff may retry sync rows", frappe.PermissionError)
	row = frappe.get_doc("Helpdesk Sync Log", name)
	if row.status != "Failed":
		frappe.throw(f"Only Failed rows can be retried, not {row.status}", frappe.ValidationError)
	row.status = "Pending"
	row.next_retry_at = None
	row.save(ignore_permissions=True)
	return {"sync": row.name, "status": row.status}


@frappe.whitelist()
def sync_report() -> dict:
	"""Staff report: failures plus mail configuration health."""
	from beaverbill.beaverbill.portal.guard import is_staff

	if not is_staff():
		frappe.throw("Only staff may view the sync report", frappe.PermissionError)
	report = sync_failures()
	report["email"] = email_health()
	report["pending"] = frappe.db.count("Helpdesk Sync Log", {"status": "Pending"})
	return report


def process_helpdesk_sync() -> dict:
	"""Scheduler entry point for sync retries."""
	return process_due_syncs()
