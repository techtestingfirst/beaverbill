"""Phase 10 portal: session status, profile, and contacts."""

import frappe

from beaverbill.beaverbill.portal.guard import may_access_customer, portal_customer, portal_endpoint


@frappe.whitelist()
@portal_endpoint("portal.session_status", limit=120)
def session_status() -> dict:
	"""Describe the caller's session: user, roles, linked customer."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	customer = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	return {"user": user, "roles": frappe.get_roles(user), "customer": customer}


@frappe.whitelist()
@portal_endpoint("portal.get_profile", limit=120)
def get_profile() -> dict:
	"""Return the caller's customer profile (ownership enforced)."""
	customer = portal_customer()
	doc = frappe.get_doc("Hosting Customer", customer)
	return {
		"name": doc.name,
		"customer_name": doc.customer_name,
		"customer_type": doc.customer_type,
		"company_name": doc.company_name,
		"status": doc.status,
		"locale": doc.locale,
		"timezone": doc.timezone,
		"email_verified": doc.email_verified,
		"consent_terms": doc.consent_terms,
		"consent_marketing": doc.consent_marketing,
	}


@frappe.whitelist()
@portal_endpoint("portal.update_profile", limit=30)
def update_profile(customer_name: str | None = None, locale: str | None = None, timezone: str | None = None, consent_marketing: int | None = None) -> dict:
	"""Update safe profile fields on the caller's own record only."""
	customer = portal_customer()
	doc = frappe.get_doc("Hosting Customer", customer)
	if customer_name:
		doc.customer_name = customer_name[:200]
	if locale:
		doc.locale = locale[:20]
	if timezone:
		doc.timezone = timezone[:60]
	if consent_marketing is not None:
		doc.consent_marketing = 1 if int(consent_marketing) else 0
	doc.save()
	return get_profile()


@frappe.whitelist()
@portal_endpoint("portal.list_contacts", limit=120)
def list_contacts() -> dict:
	"""List billing/technical contacts on the caller's record."""
	customer = portal_customer()
	rows = frappe.get_all(
		"Hosting Customer Contact",
		filters={"customer": customer},
		fields=["name", "contact_type", "full_name", "email", "phone", "is_primary"],
		order_by="creation asc",
	)
	return {"customer": customer, "contacts": rows}


def _own_contact(name: str, user=None) -> object:
	doc = frappe.get_doc("Hosting Customer Contact", name)
	if not may_access_customer(doc.customer, user):
		frappe.throw(f"Contact {name} does not belong to this customer", frappe.PermissionError)
	return doc


@frappe.whitelist()
@portal_endpoint("portal.add_contact", limit=30)
def add_contact(contact_type: str, full_name: str, email: str, phone: str | None = None) -> dict:
	"""Add a billing/technical contact to the caller's record."""
	customer = portal_customer()
	if contact_type not in ("Billing", "Technical", "Other"):
		frappe.throw("contact_type must be Billing, Technical, or Other", frappe.ValidationError)
	doc = frappe.get_doc(
		{
			"doctype": "Hosting Customer Contact",
			"customer": customer,
			"contact_type": contact_type,
			"full_name": full_name[:200],
			"email": email[:200],
			"phone": (phone or "")[:50],
		}
	).insert()
	return {"contact": doc.name}


@frappe.whitelist()
@portal_endpoint("portal.update_contact", limit=30)
def update_contact(name: str, full_name: str | None = None, email: str | None = None, phone: str | None = None) -> dict:
	"""Edit the caller's own contact."""
	doc = _own_contact(name)
	if full_name:
		doc.full_name = full_name[:200]
	if email:
		doc.email = email[:200]
	if phone is not None:
		doc.phone = phone[:50]
	doc.save()
	return {"contact": doc.name}


@frappe.whitelist()
@portal_endpoint("portal.delete_contact", limit=30)
def delete_contact(name: str) -> dict:
	"""Remove the caller's own contact."""
	doc = _own_contact(name)
	doc.delete()
	return {"deleted": name}
