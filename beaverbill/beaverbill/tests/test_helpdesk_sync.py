"""Phase 12 tests: helpdesk sync, mapping, links, visibility, tickets."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from beaverbill.beaverbill import helpdesk_sync as bridge
from beaverbill.beaverbill.portal import support


def wipe():
	for dt in [
		"Ticket Reference",
		"Helpdesk Sync Log",
		"HD Ticket Comment",
		"HD Ticket",
		"HD Customer",
		"Contact",
		"Hosting Customer Contact",
		"Hosting DNS Record",
		"Hosting Domain",
		"Hosting Invoice Item",
		"Hosting Invoice",
		"Hosting Order Item",
		"Hosting Order",
		"Hosting Service",
		"Hosting Subscription",
		"Hosting Product",
		"Hosting Customer",
	]:
		try:
			for name in frappe.get_all(dt, pluck="name"):
				frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
		except Exception:
			continue
	frappe.db.commit()


def ensure_user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Phase12", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	bridge.grant_portal_roles(email)
	return email


def ensure_customer(user, name="P12 Buyer"):
	existing = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	if existing:
		return existing
	return frappe.get_doc(
		{"doctype": "Hosting Customer", "customer_name": name,
		 "primary_user": user, "status": "Active"}
	).insert().name


def ensure_product(name="Phase12 Small"):
	if not frappe.db.exists("Hosting Product Group", "Phase12 Group"):
		frappe.get_doc({"doctype": "Hosting Product Group", "product_group_name": "Phase12 Group"}).insert()
	if frappe.db.exists("Hosting Product", name):
		return name
	return frappe.get_doc(
		{"doctype": "Hosting Product", "product_name": name, "product_group": "Phase12 Group",
		 "billing_cycle": "Monthly", "price": 10, "currency": "USD"}
	).insert().name


class TestHelpdeskSync(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		bridge.SYNC_FAULTS.clear()
		frappe.set_user("Administrator")
		self.assertTrue(bridge.helpdesk_available())
		self.assertTrue(bridge.SAME_SITE_DEPLOYMENT)
		self.user_a = ensure_user("phase12a@example.com")
		self.user_b = ensure_user("phase12b@example.com")
		self.customer_a = ensure_customer(self.user_a)
		self.customer_b = ensure_customer(self.user_b, "P12 Other")
		self.product = ensure_product()

	def tearDown(self):
		bridge.SYNC_FAULTS.clear()
		frappe.set_user("Administrator")
		wipe()

	def test_customer_source_of_truth_and_idempotency(self):
		first = bridge.sync_customer(self.customer_a)
		self.assertTrue(first["hd_customer"])
		hd = frappe.get_doc("HD Customer", first["hd_customer"])
		self.assertEqual(hd.email_id, self.user_a)
		second = bridge.sync_customer(self.customer_a)
		self.assertTrue(second.get("duplicate_request"))
		self.assertEqual(second["hd_customer"], first["hd_customer"])
		self.assertEqual(
			len(frappe.get_all("HD Customer", {"email_id": self.user_a})), 1)

	def test_contact_sync_idempotent(self):
		contact = frappe.get_doc(
			{"doctype": "Hosting Customer Contact", "customer": self.customer_a,
			 "contact_type": "Billing", "full_name": "A Acct", "email": "acct12@example.com"}
		).insert().name
		first = bridge.sync_contact(contact)
		second = bridge.sync_contact(contact)
		self.assertTrue(second.get("duplicate_request"))
		hd_name = bridge.synced_hd_name("Customer", self.customer_a)
		members = frappe.get_doc("HD Customer", hd_name).contacts
		self.assertTrue([m for m in members if m.contact_name == first["contact"]])

	def test_failure_then_scheduler_recovery(self):
		bridge.SYNC_FAULTS["customer"] = "helpdesk timeout"
		bad = bridge.sync_customer(self.customer_a)
		self.assertIsNone(bad["hd_customer"])
		row = frappe.db.get_value("Helpdesk Sync Log",
								  {"entity_type": "Customer", "entity": self.customer_a},
								  ["name", "status"], as_dict=True)
		self.assertIsNotNone(row)
		bridge.SYNC_FAULTS.clear()
		# Mature the backoff so the scheduler picks the row up immediately.
		frappe.db.set_value(
			"Helpdesk Sync Log",
			{"entity_type": "Customer", "entity": self.customer_a},
			"next_retry_at", "2020-01-01 00:00:00",
		)
		ran = bridge.process_due_syncs()
		self.assertGreaterEqual(ran["synced"], 1)
		self.assertIsNotNone(bridge.synced_hd_name("Customer", self.customer_a))

	def test_failure_report_and_retry_action(self):
		bridge.SYNC_FAULTS["customer"] = "boom"
		for _ in range(6):
			bridge.SYNC_FAULTS["customer"] = "boom"
			bridge.sync_customer(self.customer_a, idempotency_key="p12-retry-1")
		frappe.set_user("Administrator")
		report = bridge.sync_report()
		self.assertTrue([f for f in report["failures"] if f["entity"] == self.customer_a])
		self.assertIn("inbound_configured", report["email"])
		row = frappe.db.get_value("Helpdesk Sync Log", {"idempotency_key": "p12-retry-1"}, "name")
		bridge.SYNC_FAULTS.clear()
		out = bridge.retry_sync(row)
		self.assertEqual(out["status"], "Pending")
		ran = bridge.process_due_syncs()
		self.assertGreaterEqual(ran["synced"], 1)

	def test_status_priority_team_mapping(self):
		self.assertEqual(bridge.portal_status("Replied"), "In Progress")
		self.assertEqual(bridge.portal_status("Mystery"), "Mystery")
		priority = bridge.resolve_priority("Nope")
		self.assertIsNone(priority)
		self.assertEqual(bridge.resolve_priority("High"), "High")
		self.assertIsNone(bridge.resolve_team("Nope"))
		team = frappe.get_all("HD Team", pluck="name", limit=1)
		if team:
			self.assertEqual(bridge.resolve_team(team[0]), team[0])

	def test_ticket_create_links_and_visibility(self):
		frappe.set_user("Administrator")
		svc = frappe.get_doc(
			{"doctype": "Hosting Service", "customer": self.customer_a,
			 "status": "Pending", "product": self.product, "billing_cycle": "Monthly"}
		).insert()
		frappe.set_user(self.user_a)
		opened = support.create_ticket.__wrapped__(
			"Phase12 outage", "Service is down", service=svc.name, idempotency_key="p12-t-1")
		ticket = opened["ticket"]
		hd = frappe.db.get_value("HD Ticket", ticket, ["customer", "raised_by"], as_dict=True)
		self.assertEqual(hd.raised_by, self.user_a)
		self.assertEqual(hd.customer, bridge.synced_hd_name("Customer", self.customer_a))
		links = bridge.ticket_links(ticket)
		self.assertEqual(links["service"], svc.name)
		dup = support.create_ticket.__wrapped__(
			"Phase12 outage", "Service is down", service=svc.name, idempotency_key="p12-t-1")
		self.assertTrue(dup.get("duplicate_request"))
		# Agent-authored HD comments stay internal; customer comments show.
		frappe.set_user("Administrator")
		agent_note = frappe.get_doc(
			{"doctype": "HD Ticket Comment", "reference_ticket": ticket,
			 "content": "internal: escalate", "commented_by": "Administrator"}
		).insert(ignore_permissions=True)
		mine = frappe.get_doc(
			{"doctype": "HD Ticket Comment", "reference_ticket": ticket,
			 "content": "still down here", "commented_by": self.user_a}
		).insert(ignore_permissions=True)
		frappe.set_user(self.user_a)
		shown = bridge.visible_comments(ticket, self.user_a)
		bodies = [c["content"] for c in shown]
		self.assertIn("still down here", bodies)
		self.assertNotIn("internal: escalate", bodies)
		frappe.set_user("Administrator")
		staff_shown = bridge.visible_comments(ticket, "Administrator")
		self.assertIn("internal: escalate", [c["content"] for c in staff_shown])
		_ = (agent_note, mine)

	def test_cross_customer_link_and_read_denied(self):
		frappe.set_user("Administrator")
		svc_b = frappe.get_doc(
			{"doctype": "Hosting Service", "customer": self.customer_b,
			 "status": "Pending", "product": self.product, "billing_cycle": "Monthly"}
		).insert()
		frappe.set_user(self.user_b)
		opened = support.create_ticket.__wrapped__("B issue", "help", service=svc_b.name)
		frappe.set_user(self.user_a)
		with self.assertRaises(frappe.PermissionError):
			support.create_ticket.__wrapped__("Sneaky", "x", service=svc_b.name)
		with self.assertRaises(frappe.PermissionError):
			support.ticket_detail.__wrapped__(opened["ticket"])

	def test_sla_snapshot_and_email_health(self):
		frappe.set_user(self.user_a)
		opened = support.create_ticket.__wrapped__("SLA check", "what is my sla?")
		sla = bridge.ticket_sla(opened["ticket"])
		self.assertIn("response_by", sla)
		health = bridge.email_health()
		self.assertTrue(health["same_site"])
		self.assertIn("inbound_configured", health)

	def test_attachment_ownership(self):
		frappe.set_user(self.user_a)
		with self.assertRaises(frappe.ValidationError):
			support.create_ticket.__wrapped__("Files", "see attached",
											  attachments='["/files/ghost-12.png"]')
