"""Phase 13 identity helpers: scoped tokens, sessions, login throttle.

Separated from `security.py` by responsibility. All token values are
hashed (SHA-256) before storage; raw values appear only once, at issue.
"""

from __future__ import annotations

import hashlib
import secrets

import frappe
from frappe.utils import add_to_date, now_datetime

from beaverbill.beaverbill.security import (
	can_manage_credentials,
	is_staff,
	log_security_event,
)

LOGIN_FAIL_LIMIT = 5
LOGIN_FAIL_WINDOW_SEC = 15 * 60
LOGIN_LOCK_SEC = 15 * 60

SESSION_TTL_HOURS = 12


def get_session_policy() -> dict:
	"""Published session limits: TTL, MFA expectation, revocation support."""
	return {
		"session_ttl_hours": SESSION_TTL_HOURS,
		"admin_mfa": "via Frappe Two Factor Authentication",
		"customer_mfa": "optional via Frappe Two Factor Authentication",
		"revocation": "beaverbill.beaverbill.security_tokens.revoke_user_sessions",
		"verification_ttl_hours": 24,
		"console_ttl_minutes": 15,
	}


def _fail_key(login: str) -> str:
	return f"security-login-fail:{login}"


def _lock_key(login: str) -> str:
	return f"security-login-lock:{login}"


def check_login_throttle(login: str) -> None:
	"""Block password attempts while a brute-force lock is active."""
	if frappe.cache().get_value(_lock_key(login or "")):
		frappe.throw("Too many failed logins; try again later",
			frappe.RateLimitExceededError)


def record_login_attempt(login: str, success: bool) -> None:
	"""Count failures; lock the login after LOGIN_FAIL_LIMIT misses."""
	cache = frappe.cache()
	if success:
		cache.delete_value(_fail_key(login))
		return
	count = int(cache.get_value(_fail_key(login)) or 0) + 1
	cache.set_value(_fail_key(login), count, expires_in_sec=LOGIN_FAIL_WINDOW_SEC)
	if count >= LOGIN_FAIL_LIMIT:
		cache.set_value(_lock_key(login), 1, expires_in_sec=LOGIN_LOCK_SEC)
		log_security_event("auth.login_lock", "Denied", f"locked {login}")


def _hash_token(token: str) -> str:
	return hashlib.sha256(token.encode()).hexdigest()


@frappe.whitelist()
def issue_scoped_token(user: str, scopes: str,
	ttl_hours: int = 12) -> dict:
	"""Staff-only: mint a hashed, expiring, scope-limited API token."""
	if not is_staff():
		log_security_event("token.issue", "Denied", f"for {user}")
		frappe.throw("Only staff may issue API tokens", frappe.PermissionError)
	token = secrets.token_urlsafe(32)
	doc = frappe.get_doc({
		"doctype": "Scoped API Token",
		"user": user,
		"prefix": token[:8],
		"token_hash": _hash_token(token),
		"scopes": scopes,
		"expires_at": add_to_date(now_datetime(), hours=int(ttl_hours or 12)),
		"revoked": 0,
	}).insert(ignore_permissions=True)
	log_security_event("token.issue", "OK", f"for {user} scopes={scopes}")
	return {"token": token, "name": doc.name,
		"expires_at": str(doc.expires_at)}


def verify_scoped_token(token: str, required_scope: str) -> str:
	"""Check a bearer token against hash, expiry, revocation, and scope."""
	digest = _hash_token(token or "")
	name = frappe.db.get_value("Scoped API Token", {"token_hash": digest}, "name")
	if not name:
		frappe.throw("Invalid API token", frappe.PermissionError)
	doc = frappe.get_doc("Scoped API Token", name)
	if doc.revoked:
		frappe.throw("API token is revoked", frappe.PermissionError)
	if doc.expires_at and str(doc.expires_at) < str(now_datetime()):
		frappe.throw("API token has expired", frappe.PermissionError)
	scopes = {part.strip() for part in str(doc.scopes or "").split(",") if part.strip()}
	if required_scope not in scopes and "*" not in scopes:
		frappe.throw(f"Token lacks scope {required_scope}", frappe.PermissionError)
	doc.last_used_at = now_datetime()
	doc.save(ignore_permissions=True)
	return doc.user


@frappe.whitelist()
def revoke_scoped_token(name: str) -> dict:
	"""Staff-only: revoke a scoped token so it can never verify again."""
	if not is_staff():
		frappe.throw("Only staff may revoke API tokens", frappe.PermissionError)
	doc = frappe.get_doc("Scoped API Token", name)
	doc.revoked = 1
	doc.save(ignore_permissions=True)
	log_security_event("token.revoke", "OK", name)
	return {"token": name, "revoked": 1}


@frappe.whitelist()
def revoke_user_sessions(user: str) -> dict:
	"""Staff-only: drop active sessions for a login (theft/lockout response)."""
	if not is_staff():
		frappe.throw("Only staff may revoke sessions", frappe.PermissionError)
	count = 0
	for row in frappe.get_all("Sessions", filters={"user": user}, pluck="name"):
		try:
			frappe.delete_doc("Sessions", row, ignore_permissions=True, force=True)
			count += 1
		except Exception:
			continue
	frappe.cache().delete_value(f"session:{user}")
	log_security_event("session.revoke", "OK", f"{user} ({count} sessions)")
	return {"user": user, "revoked_sessions": count}


@frappe.whitelist()
def rotate_provider_credential(account: str, field: str) -> dict:
	"""Staff-only marker: record a credential rotation without logging secrets."""
	if not can_manage_credentials():
		log_security_event("credential.rotation", "Denied", account)
		frappe.throw("Not permitted to rotate provider credentials", frappe.PermissionError)
	if field not in ("api_key", "api_secret"):
		frappe.throw("Only api_key and api_secret rotate", frappe.ValidationError)
	frappe.db.set_value("Hosting Provider Account", account, "modified",
		now_datetime(), update_modified=False)
	log_security_event("credential.rotation", "OK", f"{account}.{field}")
	return {"account": account, "field": field, "rotated": True}
