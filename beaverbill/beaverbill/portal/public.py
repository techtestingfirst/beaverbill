"""Phase 11 public portal APIs: signup and email verification (guest).

Login, logout, and password reset reuse the Frappe session endpoints
(`login`, `logout`, `frappe.core.doctype.user.user.reset_password`);
only registration needs Beaver Bill records, so only it lives here.
"""

import re
import secrets

import frappe
from frappe.utils import now_datetime

from beaverbill.beaverbill.portal.guard import audit, check_rate

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
VERIFICATION_TTL = 24 * 3600


def _token_key(token: str) -> str:
	return f"portal-verify:{token}"


def _pending_key(email: str) -> str:
	return f"portal-verify-pending:{email.strip().lower()}"


def _validate_signup(full_name: str, email: str, password: str) -> str:
	name = (full_name or "").strip()
	mail = (email or "").strip().lower()
	if len(name) < 2:
		frappe.throw("Full name is required", frappe.ValidationError)
	if not EMAIL_RE.match(mail):
		frappe.throw("Enter a valid email address", frappe.ValidationError)
	if len(password or "") < MIN_PASSWORD_LENGTH:
		frappe.throw(
			f"Password must be at least {MIN_PASSWORD_LENGTH} characters", frappe.ValidationError
		)
	return mail


@frappe.whitelist(allow_guest=True)
def signup(full_name: str, password: str, email: str) -> dict:
	"""Register a portal login plus its Hosting Customer record."""
	mail = _validate_signup(full_name, email, password)
	check_rate("portal.signup", 5, 3600, user=f"guest:{mail}")
	if frappe.db.exists("User", mail):
		audit("portal.signup", "Denied", f"duplicate signup for {mail}", user="Guest")
		frappe.throw("This email is already registered. Try logging in.", frappe.ValidationError)
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": mail,
			"first_name": full_name.strip()[:140],
			"new_password": password,
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)
	from beaverbill.beaverbill import helpdesk_sync as bridge

	# Role assignment needs an empowered session; guests cannot edit User.
	previous_user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		bridge.grant_portal_roles(mail)
	finally:
		frappe.set_user(previous_user)
	customer = frappe.get_doc(
		{
			"doctype": "Hosting Customer",
			"customer_name": full_name.strip()[:200],
			"customer_type": "Individual",
			"primary_user": mail,
			"status": "Active",
			"email_verified": 0,
			"consent_terms": 1,
			"consent_datetime": now_datetime(),
		}
	).insert(ignore_permissions=True)
	token = _issue_token(mail)
	audit("portal.signup", "OK", f"registered {mail}", user=mail)
	return {"user": mail, "customer": customer.name, "verification_sent": bool(token)}


def _issue_token(mail: str) -> str | None:
	token = secrets.token_hex(24)
	frappe.cache().set_value(_token_key(token), mail, expires_in_sec=VERIFICATION_TTL)
	frappe.cache().set_value(_pending_key(mail), token, expires_in_sec=VERIFICATION_TTL)
	try:
		app_url = frappe.utils.get_url()
		frappe.sendmail(
			recipients=[mail],
			subject="Verify your Beaver Bill account",
			message=f"Welcome! Verify your email within 24 hours: {app_url}/beaverbill/verify?token={token}",
		)
	except Exception:
		pass
	return token


@frappe.whitelist(allow_guest=True)
def verify_email(token: str) -> dict:
	"""Confirm a verification token; marks the customer email verified."""
	mail = frappe.cache().get_value(_token_key(token or ""))
	if not mail:
		audit("portal.verify_email", "Denied", "invalid or expired token", user="Guest")
		frappe.throw("Verification link is invalid or expired", frappe.ValidationError)
	customer = frappe.db.get_value("Hosting Customer", {"primary_user": mail}, "name")
	if customer:
		frappe.db.set_value("Hosting Customer", customer, "email_verified", 1)
	frappe.cache().delete_value(_token_key(token))
	frappe.cache().delete_value(_pending_key(mail))
	audit("portal.verify_email", "OK", f"verified {mail}", user=mail)
	return {"user": mail, "verified": True}


@frappe.whitelist(allow_guest=True)
def resend_verification(email: str) -> dict:
	"""Re-send the verification email to an unverified account."""
	mail = (email or "").strip().lower()
	check_rate("portal.resend_verification", 5, 3600, user=f"guest:{mail}")
	customer = frappe.db.get_value(
		"Hosting Customer", {"primary_user": mail}, ["name", "email_verified"], as_dict=True
	)
	if customer and not int(customer.email_verified or 0):
		_issue_token(mail)
		audit("portal.resend_verification", "OK", mail, user="Guest")
	# Always report success so addresses cannot be enumerated.
	return {"sent": True}
