"""Phase 13 tests: role matrix, ownership denial, audit, tokens, validators."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from beaverbill.beaverbill import permissions, security
from beaverbill.beaverbill import security_tokens as tokens
from beaverbill.beaverbill.portal import guard


def ensure_user(email, first="Phase13"):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": first, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return email


def ensure_customer(user, name="Buyer13"):
	existing = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	if existing:
		return existing
	return frappe.get_doc(
		{"doctype": "Hosting Customer", "customer_name": name, "primary_user": user, "status": "Active"}
	).insert().name


def wipe_security():
	for dt in ["Scoped API Token", "Security Audit Log", "Portal Audit Event"]:
		try:
			for name in frappe.get_all(dt, pluck="name"):
				frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
		except Exception:
			continue
	frappe.db.commit()


class TestRoleMatrix(IntegrationTestCase):
	def test_matrix_separates_staff_privileges(self):
		matrix = security.get_role_matrix()
		self.assertTrue(matrix["System Manager"]["manage_users"])
		self.assertTrue(matrix["Hosting Admin"]["manage_credentials"])
		self.assertFalse(matrix["Hosting Support"]["manage_credentials"])
		self.assertFalse(matrix["Hosting Support"]["replay_events"])
		self.assertFalse(matrix["Hosting Customer"]["desk"])
		self.assertTrue(matrix["Hosting Customer"]["portal"])
		self.assertFalse(matrix["Guest"]["portal"])

	def test_require_roles_denies_customer(self):
		@security.require_roles("Hosting Admin", "System Manager")
		def staff_only():
			return "ok"

		frappe.set_user("Administrator")
		self.assertEqual(staff_only(), "ok")
		user = ensure_user("phase13-cust@example.com")
		ensure_customer(user)
		frappe.get_doc("User", user).add_roles("Hosting Customer")
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			staff_only()
		frappe.set_user("Administrator")


class TestOwnershipAndAudit(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.user_a = ensure_user("phase13a@example.com")
		self.user_b = ensure_user("phase13b@example.com")
		self.customer_a = ensure_customer(self.user_a, "A13")
		self.customer_b = ensure_customer(self.user_b, "B13")
		for user in (self.user_a, self.user_b):
			try:
				frappe.get_doc("User", user).add_roles("Hosting Customer")
			except Exception:
				pass

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_cross_customer_denied(self):
		frappe.set_user(self.user_b)
		self.assertFalse(guard.may_access_customer(self.customer_a, self.user_b))
		self.assertTrue(guard.may_access_customer(self.customer_b, self.user_b))
		doc = frappe._dict({"customer": self.customer_b})
		self.assertTrue(permissions.check_service_ownership(doc, "read", self.user_b))
		other = frappe._dict({"customer": self.customer_a})
		self.assertFalse(permissions.check_service_ownership(other, "read", self.user_b))

	def test_security_audit_log_immutable_and_scrubbed(self):
		frappe.set_user("Administrator")
		wipe_security()
		security.log_security_event("credential.rotation", "OK",
			"rotated api_secret=topsecretvalue123")
		rows = frappe.get_all("Security Audit Log",
			filters={"action": "credential.rotation"})
		self.assertTrue(rows)
		doc = frappe.get_doc("Security Audit Log", rows[0].name)
		self.assertNotIn("topsecretvalue123", doc.detail or "")
		doc.detail = "tampered"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		frappe.set_user("Administrator")

	def test_staff_only_records_hidden_from_customers(self):
		frappe.set_user(self.user_a)
		self.assertEqual(
			permissions.security_audit_log_query_conditions(self.user_a), "1=0")
		self.assertFalse(permissions.check_staff_only(
			frappe._dict({}), "read", self.user_a))
		frappe.set_user("Administrator")
		self.assertEqual(
			permissions.security_audit_log_query_conditions("Administrator"), "")
		self.assertTrue(permissions.check_staff_only(
			frappe._dict({}), "read", "Administrator"))


class TestScopedTokens(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		wipe_security()
		self.user = ensure_user("phase13-token@example.com")
		ensure_customer(self.user)

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe_security()

	def test_issue_verify_scope_revoke(self):
		issued = tokens.issue_scoped_token(self.user, "invoices:read")
		self.assertIn("token", issued)
		stored = frappe.get_doc("Scoped API Token", issued["name"])
		self.assertNotEqual(stored.token_hash, issued["token"])
		self.assertEqual(tokens.verify_scoped_token(issued["token"], "invoices:read"),
			self.user)
		with self.assertRaises(frappe.PermissionError):
			tokens.verify_scoped_token(issued["token"], "refunds:write")
		tokens.revoke_scoped_token(issued["name"])
		with self.assertRaises(frappe.PermissionError):
			tokens.verify_scoped_token(issued["token"], "invoices:read")

	def test_expired_token_rejected(self):
		issued = tokens.issue_scoped_token(self.user, "invoices:read")
		doc = frappe.get_doc("Scoped API Token", issued["name"])
		doc.expires_at = add_to_date(now_datetime(), hours=-1)
		doc.save(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			tokens.verify_scoped_token(issued["token"], "invoices:read")

	def test_customer_cannot_issue(self):
		frappe.get_doc("User", self.user).add_roles("Hosting Customer")
		frappe.set_user(self.user)
		with self.assertRaises(frappe.PermissionError):
			tokens.issue_scoped_token(self.user, "invoices:read")
		frappe.set_user("Administrator")


class TestValidators(IntegrationTestCase):
	def test_secret_scrubbing(self):
		clean = security.scrub_secrets({"api_secret": "abc", "name": "x"})
		self.assertEqual(clean["api_secret"], "<redacted>")
		self.assertEqual(clean["name"], "x")
		text = security.scrub_text("api_secret=supersecret123 ok")
		self.assertNotIn("supersecret123", text)

	def test_upload_allowlist(self):
		security.validate_upload("ticket.png", "image/png", 1024)
		with self.assertRaises(frappe.ValidationError):
			security.validate_upload("evil.exe", "application/x-msdownload", 100)
		with self.assertRaises(frappe.ValidationError):
			security.validate_upload("big.pdf", "application/pdf", 99 * 1024 * 1024)
		with self.assertRaises(frappe.ValidationError):
			security.validate_upload("../evil.png", "image/png", 100)

	def test_ssrf_blocklist(self):
		security.validate_outbound_url("https://api.hetzner.cloud/v1")
		for bad in ("http://169.254.169.254/latest", "http://127.0.0.1:8000/x",
				"http://10.0.0.5/hook", "ftp://example.com/x",
				"http://localhost:3000/x"):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				security.validate_outbound_url(bad)

	def test_provider_response_shape(self):
		security.validate_provider_response({"status": "Success", "ip": "1.2.3.4"})
		with self.assertRaises(frappe.ValidationError):
			security.validate_provider_response(["not", "a", "dict"])
		with self.assertRaises(frappe.ValidationError):
			security.validate_provider_response({"nested": {"deep": 1}})

	def test_login_throttle_locks(self):
		login = "phase13-brute@example.com"
		frappe.cache().delete_value(f"security-login-fail:{login}")
		frappe.cache().delete_value(f"security-login-lock:{login}")
		for _ in range(5):
			tokens.record_login_attempt(login, False)
		with self.assertRaises(frappe.RateLimitExceededError):
			tokens.check_login_throttle(login)
		frappe.cache().delete_value(f"security-login-fail:{login}")
		frappe.cache().delete_value(f"security-login-lock:{login}")

	def test_session_policy_and_headers(self):
		policy = tokens.get_session_policy()
		self.assertIn("session_ttl_hours", policy)
		headers = security.get_security_headers()
		self.assertIn("Content-Security-Policy", headers)
		self.assertIn("X-Frame-Options", headers)
