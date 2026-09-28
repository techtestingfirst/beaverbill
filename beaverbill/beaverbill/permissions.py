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
	"""Hook: staff pass; customers read and update only their own record."""
	user = user or frappe.session.user
	if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
		return True
	if customer_of_user(user) != doc.get("name"):
		return False
	return ptype in ("read", "write")


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


def _caller(user=None):
	"""Return (user, hosting_customer) for ownership checks."""
	user = user or frappe.session.user
	return user, customer_of_user(user)


def _staff_or_condition(user, condition):
	if set(frappe.get_roles(user or frappe.session.user)).intersection(set(STAFF_ROLES)):
		return ""
	if not customer_of_user(user or frappe.session.user):
		return "1=0"
	return condition


def _owned_table_condition(table, user, customer, user_fields=(), customer_fields=()):
	"""OR condition matching either the User link or the Hosting Customer link."""
	clauses = []
	if user_fields:
		clauses.extend(f"`{table}`.`{field}` = {frappe.db.escape(user)}" for field in user_fields)
	if customer_fields and customer:
		clauses.extend(f"`{table}`.`{field}` = {frappe.db.escape(customer)}" for field in customer_fields)
	if not clauses:
		return "1=0"
	return "(" + " OR ".join(clauses) + ")"


def portal_owned_query_conditions(table, user_fields=(), customer_fields=()):
	"""Factory for portal ownership list filters."""

	def conditions(user=None):
		user = user or frappe.session.user
		if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
			return ""
		customer = customer_of_user(user)
		if not customer and not user_fields:
			return "1=0"
		return _owned_table_condition(table, user, customer, user_fields, customer_fields)

	return conditions


hosting_order_query_conditions = portal_owned_query_conditions(
	"tabHosting Order", user_fields=("customer",), customer_fields=("hosting_customer",)
)
hosting_invoice_query_conditions = portal_owned_query_conditions(
	"tabHosting Invoice", user_fields=("customer",), customer_fields=("hosting_customer",)
)
hosting_subscription_query_conditions = portal_owned_query_conditions(
	"tabHosting Subscription", user_fields=("customer",), customer_fields=("customer",)
)
hosting_payment_query_conditions = portal_owned_query_conditions(
	"tabHosting Payment Transaction", user_fields=("customer",)
)
hosting_payment_method_query_conditions = portal_owned_query_conditions(
	"tabHosting Payment Method", user_fields=("customer",)
)


def _customer_table_conditions(table):
	def conditions(user=None):
		user = user or frappe.session.user
		if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
			return ""
		customer = customer_of_user(user)
		if not customer:
			return "1=0"
		return f"`{table}`.`customer` = {frappe.db.escape(customer)}"

	return conditions


hosting_contact_query_conditions = _customer_table_conditions("tabHosting Customer Contact")
hosting_domain_query_conditions = _customer_table_conditions("tabHosting Domain")
ssl_certificate_query_conditions = _customer_table_conditions("tabSSL Certificate")
service_backup_query_conditions = _customer_table_conditions("tabService Backup")
restore_request_query_conditions = _customer_table_conditions("tabRestore Request")
service_addon_query_conditions = _customer_table_conditions("tabService Addon")
service_action_query_conditions = _customer_table_conditions("tabService Action")
service_usage_query_conditions = _customer_table_conditions("tabService Storage Usage")


def hosting_dns_query_conditions(user=None):
	user = user or frappe.session.user
	if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
		return ""
	customer = customer_of_user(user)
	if not customer:
		return "1=0"
	return (
		"`tabHosting DNS Record`.`domain` in (select `name` from `tabHosting Domain`"
		f" where `customer` = {frappe.db.escape(customer)})"
	)


def customer_notification_query_conditions(user=None):
	user = user or frappe.session.user
	if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
		return ""
	customer = customer_of_user(user)
	clauses = []
	if customer:
		clauses.append(f"`tabCustomer Notification`.`customer` = {frappe.db.escape(customer)}")
	clauses.append(f"`tabCustomer Notification`.`user` = {frappe.db.escape(user)}")
	return "(" + " OR ".join(clauses) + ")"


def _staff_only_query_conditions(user=None):
	"""Security records are staff-visible only; customers see nothing."""
	user = user or frappe.session.user
	if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
		return ""
	return "1=0"


security_audit_log_query_conditions = _staff_only_query_conditions
scoped_api_token_query_conditions = _staff_only_query_conditions


def check_staff_only(doc, ptype="read", user=None):
	"""Staff pass; customers and guests are always denied."""
	user = user or frappe.session.user
	return bool(set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)))


def _owned_doc(doc, user, write=False, delete=False):
	"""True when the doc's user/customer links belong to the caller."""
	customer = customer_of_user(user)
	values = [doc.get("customer"), doc.get("hosting_customer"), doc.get("user")]
	owned = user in values or (customer and customer in values)
	if not owned:
		return False
	return True


def check_owned_doc(write=False, delete=False):
	"""Factory for portal ownership document checks."""

	def check(doc, ptype="read", user=None):
		user = user or frappe.session.user
		if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
			return True
		if ptype == "read":
			return _owned_doc(doc, user)
		if ptype == "write":
			return write and _owned_doc(doc, user)
		if ptype == "create":
			return _owned_doc(doc, user)
		if ptype == "delete":
			return delete and _owned_doc(doc, user)
		return False

	return check


def check_dns_ownership(doc, ptype="read", user=None):
	"""DNS rows carry no customer field; ownership resolves via the domain."""
	user = user or frappe.session.user
	if set(frappe.get_roles(user)).intersection(set(STAFF_ROLES)):
		return True
	if not doc.get("domain"):
		return False
	domain_customer = frappe.db.get_value("Hosting Domain", doc.domain, "customer")
	if domain_customer != customer_of_user(user):
		return False
	return ptype in ("read", "write", "create")


check_order_ownership = check_owned_doc(write=True)
check_contact_ownership = check_owned_doc(write=True, delete=True)
check_domain_ownership = check_owned_doc(write=True)
check_addon_ownership = check_owned_doc(write=True)
check_invoice_ownership = check_owned_doc(write=True)
check_payment_ownership = check_owned_doc(write=True)
check_notification_ownership = check_owned_doc(write=True)
check_action_ownership = check_owned_doc(write=True)
check_payment_method_ownership = check_owned_doc(delete=True)
check_portal_read_ownership = check_owned_doc()
