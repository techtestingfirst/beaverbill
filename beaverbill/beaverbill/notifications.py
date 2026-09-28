"""Phase 9 shared notifications: Comment audit + best-effort email."""

import frappe


def customer_email(customer: str | None) -> str | None:
	if not customer:
		return None
	if "@" in customer:
		return customer
	user = frappe.db.get_value("Hosting Customer", customer, "primary_user")
	if user and "@" in str(user):
		return str(user)
	if user:
		email = frappe.db.get_value("User", user, "email")
		return email or None
	return None


def notify(customer: str | None, subject: str, message: str, reference_doctype: str | None = None,
		   reference_name: str | None = None) -> None:
	"""Audit-log a notice and email the customer when possible. Never raises."""
	if reference_doctype and reference_name:
		try:
			frappe.get_doc(
				{
					"doctype": "Comment",
					"comment_type": "Info",
					"reference_doctype": reference_doctype,
					"reference_name": reference_name,
					"content": f"{subject}. {message}".strip()[:1000],
				}
			).insert(ignore_permissions=True)
		except Exception:
			pass
	try:
		email = customer_email(customer)
		if email:
			frappe.sendmail(recipients=[email], subject=subject, message=message)
	except Exception:
		pass


def require_staff() -> None:
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles & {"System Manager", "Hosting Admin"}:
		frappe.throw("Only staff may run this action", frappe.PermissionError)


def billable_customer(customer: str | None) -> str | None:
	"""Resolve the User that billing records key off.

	Phases 4-7 key invoices, payments, and ledger rows off User.
	Hosting Customer rows resolve through their primary user.
	"""
	if not customer:
		return None
	if "@" in customer and frappe.db.exists("User", customer):
		return customer
	user = frappe.db.get_value("Hosting Customer", customer, "primary_user")
	return user or customer
