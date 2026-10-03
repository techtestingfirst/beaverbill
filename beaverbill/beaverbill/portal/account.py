"""Phase 10 portal: session status, profile, and contacts."""

import contextlib
import socket

import frappe

from beaverbill.beaverbill.portal.guard import may_access_customer, portal_customer, portal_endpoint


@contextlib.contextmanager
def _prefer_ipv4():
	"""Resolve IPv4 first for the wrapped call only (NAT64 IPv6 stalls)."""
	original = socket.getaddrinfo

	def patched(host, port, family=0, *args, **kwargs):
		if family in (0, socket.AF_UNSPEC):
			try:
				quad_a = original(host, port, socket.AF_INET, *args, **kwargs)
			except socket.gaierror:
				quad_a = []
			if quad_a:
				return quad_a
		return original(host, port, family, *args, **kwargs)

	socket.getaddrinfo = patched
	try:
		yield
	finally:
		socket.getaddrinfo = original


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


@frappe.whitelist()
@portal_endpoint("portal.get_tax_profile", limit=60)
def get_tax_profile() -> dict:
	"""Caller tax profile with billing address + Tax ID status."""
	from beaverbill.beaverbill import pricing as pricing_engine

	customer = portal_customer()
	profile = pricing_engine.get_tax_profile(customer=customer)
	if not profile:
		return {"customer": customer, "country": "", "profile": None}
	return {
		"customer": customer,
		"country": profile.country,
		"state": profile.state,
		"address_line1": getattr(profile, "address_line1", ""),
		"address_line2": getattr(profile, "address_line2", ""),
		"city": getattr(profile, "city", ""),
		"postal_code": getattr(profile, "postal_code", ""),
		"tax_id": getattr(profile, "tax_id", ""),
		"tax_id_validated": int(getattr(profile, "tax_id_validated", 0) or 0),
		"tax_exempt": int(profile.tax_exempt or 0),
	}


@frappe.whitelist()
@portal_endpoint("portal.update_tax_profile", limit=30)
def update_tax_profile(country: str | None = None, state: str | None = None, address_line1: str | None = None, address_line2: str | None = None, city: str | None = None, postal_code: str | None = None, tax_id: str | None = None) -> dict:
	"""Save billing address + optional Tax ID. Validates ID live (stub)."""
	import frappe as _frappe

	from beaverbill.beaverbill import pricing as pricing_engine
	from beaverbill.beaverbill import taxes as tax_helper

	user = _frappe.session.user
	customer = portal_customer()
	name = _frappe.db.get_value("Hosting Customer Tax Profile", {"customer": customer}, "name")
	if not name:
		name = _frappe.db.get_value("Hosting Customer Tax Profile", {"user": user}, "name")
	if name:
		doc = _frappe.get_doc("Hosting Customer Tax Profile", name)
	else:
		doc = _frappe.get_doc({"doctype": "Hosting Customer Tax Profile", "user": user, "customer": customer})
	if country is not None:
		doc.country = (country or "")[:100]
	if state is not None:
		doc.state = (state or "")[:100]
	if address_line1 is not None:
		doc.address_line1 = (address_line1 or "")[:200]
	if address_line2 is not None:
		doc.address_line2 = (address_line2 or "")[:200]
	if city is not None:
		doc.city = (city or "")[:100]
	if postal_code is not None:
		doc.postal_code = (postal_code or "")[:20]
	if tax_id is not None:
		clean = (tax_id or "").strip()
		if clean:
			checked = tax_helper.validate_tax_id(clean, doc.country or "")
			doc.tax_id = checked["tax_id"][:50]
			doc.tax_id_validated = 1 if checked["validated"] else 0
		else:
			doc.tax_id = ""
			doc.tax_id_validated = 0
	doc.save(ignore_permissions=True)
	_ = pricing_engine.get_tax_profile(customer=customer)
	return get_tax_profile()


@frappe.whitelist()
@portal_endpoint("portal.list_countries", limit=120)
def list_countries() -> dict:
	"""All countries for the billing-address dropdown (name + ISO code)."""
	rows = frappe.get_all("Country", fields=["name", "code"], order_by="name asc")
	return {"countries": [{"name": r.name, "code": r.code} for r in rows]}


@frappe.whitelist()
@portal_endpoint("portal.lookup_postal", limit=60)
def lookup_postal(country: str, postal_code: str) -> dict:
	"""City/state autofill from postal code. Best effort, manual entry always kept."""
	code = (postal_code or "").strip()
	if not code:
		frappe.throw("postal_code is required", frappe.ValidationError)
	import re as _re

	lookup_code = _re.sub(r"[\s\-]", "", code)
	country = (country or "").strip()
	iso = frappe.db.get_value("Country", country, "code") or ""
	if len(iso) != 2:
		iso = frappe.db.get_value("Country", {"country_name": country}, "code") or ""
	iso = (iso or "").lower()
	if len(iso) != 2:
		return {"city": "", "state": "", "source": "manual"}
	import requests

	cache_key = f"portal-postal:{iso}:{lookup_code}"
	try:
		hit = frappe.cache().get_value(cache_key)
		if hit:
			import json as _json

			cached = _json.loads(hit) if isinstance(hit, str) else hit
			if cached.get("city"):
				return cached
	except Exception:
		pass
	try:
		with _prefer_ipv4():
			resp = requests.get(f"https://api.zippopotam.us/{iso}/{lookup_code}", timeout=6)
		if resp.status_code != 200 and iso == "in":
			resp = requests.get(f"https://api.postalpincode.in/pincode/{lookup_code}", timeout=6)
			if resp.status_code == 200:
				payload = resp.json() or []
				post = (payload[0].get("PostOffice") or [None])[0] if payload else None
				if payload and payload[0].get("Status") == "Success" and post:
					out = {
						"city": post.get("District") or post.get("Name", ""),
						"state": post.get("State", ""),
						"source": "postalpincode",
					}
					try:
						import json as _json2

						frappe.cache().set_value(cache_key, _json2.dumps(out), expires_in_sec=30 * 24 * 3600)
					except Exception:
						pass
					return out
			return {"city": "", "state": "", "source": "manual"}
		if resp.status_code != 200:
			return {"city": "", "state": "", "source": "manual"}
		data = resp.json() or {}
		places = data.get("places") or []
		if not places:
			return {"city": "", "state": "", "source": "manual"}
		place = places[0]
		out = {
			"city": place.get("place name", ""),
			"state": place.get("state") or place.get("state abbreviation", ""),
			"source": "zippopotam",
		}
		try:
			import json as _json

			frappe.cache().set_value(cache_key, _json.dumps(out), expires_in_sec=30 * 24 * 3600)
		except Exception:
			pass
		return out
	except Exception:
		return {"city": "", "state": "", "source": "manual"}
