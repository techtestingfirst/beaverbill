"""Row-level ownership for customer-visible DocTypes."""

import frappe

STAFF_ROLES = ("System Manager", "Hosting Admin", "Hosting Support")


def customer_of_user(user):
	return frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")


def owns_service(user, service_customer):
	return bool(service_customer) and customer_of_user(user) == service_customer


def check_service_ownership(doc, ptype="read", user=None):
	"""Hook: staff pass; customers pass only for their own services."""
	user = user or frappe.session.user
	if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
		return True
	if ptype != "read":
		return False
	return owns_service(user, doc.get("customer"))


def check_customer_ownership(doc, ptype="read", user=None):
	"""Hook: staff pass; customers pass only for their own record."""
	user = user or frappe.session.user
	if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
		return True
	if ptype != "read":
		return False
	return customer_of_user(user) == doc.get("name")


def hosting_service_query_conditions(user=None):
	"""Customers see only their own services; staff see all."""
	user = user or frappe.session.user
	if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
		return ""
	customer = customer_of_user(user)
	if not customer:
		return "1=0"
	return f"`tabHosting Service`.`customer` = {frappe.db.escape(customer)}"


def hosting_customer_query_conditions(user=None):
	"""Customers see only their own customer record; staff see all."""
	user = user or frappe.session.user
	if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
		return ""
	customer = customer_of_user(user)
	if not customer:
		return "1=0"
	return f"`tabHosting Customer`.`name` = {frappe.db.escape(customer)}"
