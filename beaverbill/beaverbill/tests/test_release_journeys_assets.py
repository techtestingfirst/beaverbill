"""Phase 14 asset journeys: domain/SSL renewal, tickets, unauthorized access."""

import frappe
from frappe.tests import IntegrationTestCase

from beaverbill.beaverbill import billing, certificates, domains
from beaverbill.beaverbill.portal import services
from beaverbill.beaverbill.tests.release_helpers import (
	ensure_customer,
	ensure_products,
	ensure_user,
	wipe,
)


class TestDomainAndCertRenewal(IntegrationTestCase):
	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.user = ensure_user("phase14-dom@example.com", "Dom14")
		self.customer = ensure_customer(self.user, "P14 Dom")
		self.small, _large = ensure_products()
		svc = frappe.get_doc({"doctype": "Hosting Service",
			"customer": self.customer, "status": "Pending", "product": self.small,
			"billing_cycle": "Monthly"}).insert()
		frappe.db.set_value("Hosting Service", svc.name, "status", "Active",
			update_modified=False)
		self.service = svc.name

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_domain_renew_and_ssl_install_renew(self):
		reg = domains.register_domain(self.customer, "example-journey.com",
			service=self.service)
		self.assertEqual(reg["status"], "Active")
		first_expiry = frappe.db.get_value("Hosting Domain", reg["domain"], "expiry_date")
		billing.post_ledger(self.user, 500, "Credit", "P14 funding")
		quoted = domains.renew_domain(reg["domain"])
		self.assertFalse(quoted["renewed"])
		total = frappe.db.get_value("Hosting Invoice", quoted["invoice"], "total_amount")
		billing.apply_credit_to_invoice(self.user, quoted["invoice"], float(total))
		renewed = domains.renew_domain(reg["domain"])
		self.assertTrue(renewed["renewed"])
		self.assertTrue(str(frappe.db.get_value(
			"Hosting Domain", reg["domain"], "expiry_date")) >= str(first_expiry))
		req = certificates.request_certificate(reg["domain"], self.customer,
			service=self.service)
		domains.add_dns_record(reg["domain"], "TXT", "_acme-challenge",
			req["validation_token"] if isinstance(req, dict) and req.get("validation_token")
			else frappe.db.get_value("SSL Certificate", req["certificate"], "validation_token"))
		cert = req["certificate"]
		checked = certificates.validate_certificate(cert)
		self.assertEqual(checked["status"], "Active")
		installed = certificates.install_certificate(cert, self.service)
		self.assertEqual(installed["service"], self.service)
		re_issued = certificates.renew_certificate(cert)
		self.assertEqual(re_issued["status"], "Failed")
		fresh_token = frappe.db.get_value("SSL Certificate", cert, "validation_token")
		domains.add_dns_record(reg["domain"], "TXT", "_acme-challenge", fresh_token)
		revalidated = certificates.validate_certificate(cert)
		self.assertEqual(revalidated["status"], "Active")


class TestTicketAndUnauthorized(IntegrationTestCase):
	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		from beaverbill.beaverbill import helpdesk_sync as bridge

		self.bridge = bridge
		if not bridge.helpdesk_available():
			self.skipTest("helpdesk not installed on this site")
		self.user_a = ensure_user("phase14a@example.com", "A14")
		self.user_b = ensure_user("phase14b@example.com", "B14")
		self.customer_a = ensure_customer(self.user_a, "P14 A")
		self.customer_b = ensure_customer(self.user_b, "P14 B")
		self.small, _large = ensure_products()
		svc = frappe.get_doc({"doctype": "Hosting Service",
			"customer": self.customer_a, "status": "Pending", "product": self.small,
			"billing_cycle": "Monthly"}).insert()
		frappe.db.set_value("Hosting Service", svc.name, "status", "Active",
			update_modified=False)
		self.service_a = svc.name

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_ticket_roundtrip_then_cross_customer_denied(self):
		frappe.set_user(self.user_a)
		created = self.bridge.create_portal_ticket("Journey outage",
			"Service is down", service=self.service_a,
			idempotency_key="phase14-ticket-1", user=self.user_a)
		self.assertFalse(created.get("duplicate_request"))
		again = self.bridge.create_portal_ticket("Journey outage",
			"Service is down", service=self.service_a,
			idempotency_key="phase14-ticket-1", user=self.user_a)
		self.assertTrue(again.get("duplicate_request"))
		frappe.set_user(self.user_b)
		with self.assertRaises(frappe.PermissionError):
			services.service_detail.__wrapped__(self.service_a)
		with self.assertRaises(frappe.PermissionError):
			self.bridge.create_portal_ticket("Hijack", "x", service=self.service_a,
				user=self.user_b)
		frappe.set_user("Administrator")
		staff_ticket = frappe.get_doc("HD Ticket", created["ticket"])
		self.assertTrue(staff_ticket.name)
