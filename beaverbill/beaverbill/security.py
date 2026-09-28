"""Phase 13 security helpers: roles, authz, audit, scrubbing, validators.

Token, session, and login-throttle helpers live in
`beaverbill.beaverbill.security_tokens` to keep this module focused.
"""

from __future__ import annotations

import functools
import ipaddress
import os
import re
from urllib.parse import urlparse

import frappe
from frappe.utils import now_datetime

STAFF_ROLES = frozenset({"System Manager", "Hosting Admin", "Hosting Support"})
CUSTOMER_ROLES = frozenset({"Hosting Customer", "HD Customer"})

# Role -> desk capabilities. Customers have no desk write access to
# billing, provider, or security records; all customer writes go
# through ownership-checked portal APIs.
ROLE_MATRIX: dict[str, dict[str, bool]] = {
	"System Manager": {"desk": True, "manage_users": True, "manage_credentials": True,
		"view_audit": True, "replay_events": True, "portal": True},
	"Hosting Admin": {"desk": True, "manage_users": False, "manage_credentials": True,
		"view_audit": True, "replay_events": True, "portal": False},
	"Hosting Support": {"desk": True, "manage_users": False, "manage_credentials": False,
		"view_audit": True, "replay_events": False, "portal": False},
	"Hosting Customer": {"desk": False, "manage_users": False, "manage_credentials": False,
		"view_audit": False, "replay_events": False, "portal": True},
	"Guest": {"desk": False, "manage_users": False, "manage_credentials": False,
		"view_audit": False, "replay_events": False, "portal": False},
}

# Actions that must leave a Security Audit Log row.
SENSITIVE_ACTIONS = frozenset({
	"credential.rotation", "credential.view", "user.role_change",
	"session.revoke", "token.issue", "token.revoke",
	"console.issue", "console.redeem", "refund.issue",
	"restore.request", "os.reinstall", "password.reset",
	"webhook.replay", "sync.retry",
})

SECRET_KEYS = ("api_key", "api_secret", "password", "secret", "token",
	"webhook_secret", "private_key", "cvv", "card_number", "pan")

ALLOWED_UPLOAD_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".pdf", ".txt", ".log"})
ALLOWED_UPLOAD_MIME = frozenset({"image/png", "image/jpeg", "application/pdf",
	"text/plain", "text/x-log"})
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

SSRF_BLOCKED_HOSTS = frozenset({"localhost", "metadata.google.internal"})
METADATA_CIDR = ipaddress.ip_network("169.254.169.254/32")

MAX_PROVIDER_RESPONSE_BYTES = 256 * 1024


def get_role_matrix() -> dict[str, dict[str, bool]]:
	"""Return the staff/customer privilege matrix (copy)."""
	return {role: dict(caps) for role, caps in ROLE_MATRIX.items()}


def is_staff(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return bool(set(frappe.get_roles(user)) & set(STAFF_ROLES))


def can_manage_credentials(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return any(ROLE_MATRIX.get(role, {}).get("manage_credentials")
		for role in frappe.get_roles(user))


def require_roles(*roles: str):
	"""Deny unless the caller holds one of the given roles."""
	allowed = set(roles)

	def decorator(fn):
		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			if not (set(frappe.get_roles(frappe.session.user)) & allowed):
				log_security_event("authz.deny", "Denied", fn.__name__)
				frappe.throw("Not permitted", frappe.PermissionError)
			return fn(*args, **kwargs)

		return wrapper

	return decorator


def log_security_event(action: str, status: str = "OK",
	detail: str = "", user: str | None = None) -> None:
	"""Append a Security Audit Log row with secrets scrubbed. Never raises."""
	try:
		frappe.get_doc({
			"doctype": "Security Audit Log",
			"user": user or frappe.session.user,
			"action": action[:140],
			"status": status if status in ("OK", "Denied", "Error") else "OK",
			"detail": scrub_text(detail or "")[:1000],
			"at": now_datetime(),
		}).insert(ignore_permissions=True)
	except Exception:
		pass


def scrub_text(text: str) -> str:
	"""Redact secret-looking key=value pairs and long tokens."""
	redacted = str(text or "")
	for key in SECRET_KEYS:
		redacted = re.sub(rf"(?i)({re.escape(key)}['\"\s:=]+)([^\s,;\"']{{3,}})",
			r"\1<redacted>", redacted)
	return redacted


def scrub_secrets(payload: dict) -> dict:
	"""Return a copy of a mapping with secret values redacted."""
	clean: dict = {}
	for key, value in dict(payload or {}).items():
		if str(key).lower() in SECRET_KEYS:
			clean[key] = "<redacted>"
		else:
			clean[key] = value
	return clean


def validate_upload(filename: str, content_type: str | None,
	size_bytes: int | None) -> None:
	"""Allowlist ticket attachment uploads. Raises ValidationError."""
	suffix = os.path.splitext(str(filename or "").lower())[1]
	if suffix not in ALLOWED_UPLOAD_SUFFIXES:
		frappe.throw(f"File type {suffix or '?'} is not allowed", frappe.ValidationError)
	if content_type and content_type not in ALLOWED_UPLOAD_MIME:
		frappe.throw(f"Content type {content_type} is not allowed", frappe.ValidationError)
	if size_bytes is not None and size_bytes > MAX_UPLOAD_BYTES:
		frappe.throw("File exceeds the 5 MB limit", frappe.ValidationError)
	if ".." in str(filename) or "/" in str(filename) or "\\" in str(filename):
		frappe.throw("Filename must not contain a path", frappe.ValidationError)


def _is_private_ip(host: str) -> bool:
	try:
		ip = ipaddress.ip_address(host)
	except ValueError:
		return False
	return ip.is_private or ip.is_loopback or ip.is_link_local or ip in METADATA_CIDR


def validate_outbound_url(url: str) -> str:
	"""SSRF guard for provider endpoints and registrar URLs."""
	parsed = urlparse(str(url or ""))
	if parsed.scheme not in ("https", "http"):
		frappe.throw("Outbound URL must use http or https", frappe.ValidationError)
	host = (parsed.hostname or "").lower()
	if not host or host in SSRF_BLOCKED_HOSTS:
		frappe.throw(f"Outbound host {host or '?'} is blocked", frappe.ValidationError)
	if _is_private_ip(host):
		frappe.throw(f"Outbound host {host} resolves to a private address",
			frappe.ValidationError)
	if parsed.port and parsed.port not in (80, 443):
		frappe.throw("Outbound URL uses a blocked port", frappe.ValidationError)
	return str(url)


def validate_provider_response(payload: object,
	limit: int = MAX_PROVIDER_RESPONSE_BYTES) -> dict:
	"""Accept only small plain-dict driver payloads; reject the rest."""
	if not isinstance(payload, dict):
		frappe.throw("Provider response must be a JSON object", frappe.ValidationError)
	text = str(payload)
	if len(text) > limit:
		frappe.throw("Provider response exceeds the size limit", frappe.ValidationError)
	for value in payload.values():
		if not isinstance(value, (str, int, float, bool, type(None))):
			frappe.throw("Provider response has an unsupported value type",
				frappe.ValidationError)
	return dict(payload)


def get_security_headers() -> dict[str, str]:
	"""Response headers every portal page and API should carry."""
	return {
		"Content-Security-Policy": "default-src 'self'; script-src 'self'; "
			"object-src 'none'; frame-ancestors 'self'",
		"X-Content-Type-Options": "nosniff",
		"X-Frame-Options": "SAMEORIGIN",
		"Referrer-Policy": "strict-origin-when-cross-origin",
	}
