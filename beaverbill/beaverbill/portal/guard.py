"""Phase 10 portal guard: Frappe session auth, ownership, rate limits, audit.

Authentication rides on the Frappe session cookie (or API key/token);
every endpoint resolves the caller to a Hosting Customer through the
User's primary-user link. Guests and logins without a customer record
are denied. Staff roles bypass ownership but every call is audited.
"""

import functools

import frappe
from frappe.utils import now_datetime

STAFF_ROLES = {"System Manager", "Hosting Admin", "Hosting Support"}


def is_staff(user=None) -> bool:
	user = user or frappe.session.user
	return bool(set(frappe.get_roles(user)) & STAFF_ROLES)


def portal_customer(user=None) -> str:
	"""Resolve the caller's Hosting Customer or raise PermissionError."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)
	customer = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	if not customer and not is_staff(user):
		frappe.throw("No hosting customer linked to this login", frappe.PermissionError)
	return customer


def may_access_customer(customer_name: str, user=None) -> bool:
	user = user or frappe.session.user
	if is_staff(user):
		return True
	return frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name") == customer_name


def _deny(message: str):
	frappe.throw(message, frappe.PermissionError)


def own_service_or_throw(service_name: str, user=None) -> object:
	doc = frappe.get_doc("Hosting Service", service_name)
	if not may_access_customer(doc.customer, user):
		_deny(f"Service {service_name} does not belong to this customer")
	return doc


def own_domain_or_throw(domain_name: str, user=None) -> object:
	doc = frappe.get_doc("Hosting Domain", domain_name)
	if not may_access_customer(doc.customer, user):
		_deny(f"Domain {domain_name} does not belong to this customer")
	return doc


def own_invoice_or_throw(invoice_name: str, user=None) -> object:
	user = user or frappe.session.user
	doc = frappe.get_doc("Hosting Invoice", invoice_name)
	if is_staff(user):
		return doc
	customer = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	if doc.customer == user or (customer and doc.hosting_customer == customer):
		return doc
	_deny(f"Invoice {invoice_name} does not belong to this customer")
	return doc


def own_subscription_or_throw(subscription_name: str, user=None) -> object:
	user = user or frappe.session.user
	doc = frappe.get_doc("Hosting Subscription", subscription_name)
	if is_staff(user):
		return doc
	customer = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	# Subscriptions key billing off User; accept either link style.
	if doc.customer == user or (customer and doc.customer == customer):
		return doc
	_deny(f"Subscription {subscription_name} does not belong to this customer")
	return doc


def check_rate(endpoint: str, limit: int, window: int = 60, user=None) -> None:
	"""Sliding-window rate limit backed by the cache. Raises when exceeded."""
	user = user or frappe.session.user
	key = f"portal-rl:{endpoint}:{user}"
	cache = frappe.cache()
	count = int(cache.get_value(key) or 0) + 1
	cache.set_value(key, count, expires_in_sec=window)
	if count > limit:
		audit(endpoint, "Rate Limited", f"{user} exceeded {limit}/{window}s", user)
		frappe.throw("Rate limit exceeded, try again shortly", frappe.RateLimitExceededError)


def audit(endpoint: str, status: str, detail: str = "", user=None) -> None:
	"""Append a portal audit event. Never raises."""
	try:
		frappe.get_doc(
			{
				"doctype": "Portal Audit Event",
				"user": user or frappe.session.user,
				"endpoint": endpoint,
				"status": status,
				"detail": (detail or "")[:1000],
				"at": now_datetime(),
			}
		).insert(ignore_permissions=True)
	except Exception:
		pass


def portal_endpoint(name: str, limit: int = 120, window: int = 60):
	"""Decorate a whitelisted portal function with rate limit + audit.

	Permission denials audit as Denied, rate trips as Rate Limited,
	other failures as Error; every outcome re-raises to the caller.
	"""

	def decorator(fn):
		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			check_rate(name, limit, window)
			try:
				result = fn(*args, **kwargs)
			except frappe.PermissionError as exc:
				audit(name, "Denied", str(exc))
				raise
			except Exception as exc:
				audit(name, "Error", f"{type(exc).__name__}: {exc}")
				raise
			audit(name, "OK", "")
			return result

		return wrapper

	return decorator
