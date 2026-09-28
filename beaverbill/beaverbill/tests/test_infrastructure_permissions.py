import frappe
from frappe.tests import IntegrationTestCase

INFRA_DOCTYPES = [
	"IPAM Subnet",
	"IPAM IP Address",
	"Server Node",
	"Datacenter Asset",
	"Hosting Provider Account",
	"Hosting Datacenter",
	"IPAM Allocation Log",
]


def make_user(email, roles):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	user.roles = []
	for role in roles:
		user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	return user.name


class TestInfrastructurePermissions(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.support = make_user("phase1-support@example.com", ["Hosting Support"])
		cls.admin = make_user("phase1-admin@example.com", ["Hosting Admin"])
		cls.customer = make_user("phase1-customer@example.com", ["Hosting Customer"])

	def test_support_read_only(self):
		for dt in INFRA_DOCTYPES:
			self.assertTrue(frappe.has_permission(dt, "read", user=self.support), dt)
			self.assertFalse(frappe.has_permission(dt, "create", user=self.support), dt)
			self.assertFalse(frappe.has_permission(dt, "write", user=self.support), dt)
			self.assertFalse(frappe.has_permission(dt, "delete", user=self.support), dt)

	def test_admin_full_access(self):
		for dt in [d for d in INFRA_DOCTYPES if d != "IPAM Allocation Log"]:
			for perm in ("read", "write", "create", "delete"):
				self.assertTrue(frappe.has_permission(dt, perm, user=self.admin), f"{dt}:{perm}")

	def test_allocation_log_is_read_only(self):
		# The log is system-written; even admins cannot create or edit entries.
		self.assertTrue(frappe.has_permission("IPAM Allocation Log", "read", user=self.admin))
		for perm in ("write", "create", "delete"):
			self.assertFalse(frappe.has_permission("IPAM Allocation Log", perm, user=self.admin), perm)

	def test_customer_no_infra_access(self):
		for dt in INFRA_DOCTYPES:
			self.assertFalse(frappe.has_permission(dt, "read", user=self.customer), dt)
			self.assertFalse(frappe.has_permission(dt, "write", user=self.customer), dt)

	def test_support_cannot_insert(self):
		frappe.set_user(self.support)
		try:
			self.assertRaises(
				frappe.PermissionError,
				frappe.get_doc({"doctype": "Server Node", "node_name": "Nope", "node_type": "Storage"}).insert,
			)
		finally:
			frappe.set_user("Administrator")

	def test_staff_reads_record_owned_by_admin(self):
		frappe.set_user("Administrator")
		node = frappe.get_doc(
			{"doctype": "Server Node", "node_name": "Perm Node", "node_type": "Hypervisor"}
		).insert()
		try:
			# No owner restriction: support reads a record owned by Administrator.
			self.assertTrue(frappe.has_permission("Server Node", "read", doc=node.name, user=self.support))
			frappe.set_user(self.support)
			try:
				fetched = frappe.get_doc("Server Node", node.name)
				self.assertEqual(fetched.node_name, "Perm Node")
			finally:
				frappe.set_user("Administrator")
		finally:
			frappe.delete_doc("Server Node", node.name, ignore_permissions=True)

	def test_customer_list_denied(self):
		frappe.set_user(self.customer)
		try:
			self.assertRaises(frappe.PermissionError, frappe.get_list, "IPAM IP Address", fields=["name"])
		finally:
			frappe.set_user("Administrator")

	def test_provider_secrets_hidden_from_customer(self):
		frappe.set_user("Administrator")
		account = frappe.get_doc(
			{
				"doctype": "Hosting Provider Account",
				"provider_name": "Perm Provider",
				"provider_type": "Custom",
				"api_secret": "topsecret",
			}
		).insert()
		try:
			frappe.set_user(self.support)
			try:
				public = account.get_public_fields()
				self.assertNotIn("api_secret", public)
				self.assertNotIn("api_key", public)
				self.assertEqual(public["provider_name"], "Perm Provider")
			finally:
				frappe.set_user("Administrator")
			frappe.set_user(self.customer)
			try:
				self.assertRaises(frappe.PermissionError, account.get_public_fields)
			finally:
				frappe.set_user("Administrator")
		finally:
			frappe.delete_doc("Hosting Provider Account", account.name, ignore_permissions=True)
