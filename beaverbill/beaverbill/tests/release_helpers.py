"""Shared fixtures for the Phase 14 release-journey suites."""

import hashlib
import hmac
import json

import frappe

from beaverbill.beaverbill.domains import SimulatedRegistrarDriver

SECRET = "phase14-test-secret"


def wipe(extra=()):
	doctypes = [
		"Portal Audit Event",
		"Security Audit Log",
		"Ticket Reference",
		"Helpdesk Sync Log",
		"Service Action",
		"Restore Request",
		"Service Backup",
		"Service Addon",
		"Service Storage Usage",
		"SSL Certificate",
		"Hosting DNS Record",
		"Hosting Domain",
		"Domain Registrar Account",
		"Hosting Service Modification Request",
		"Hosting Modification Event",
		"Resource Cleanup Task",
		"Reconciliation Result",
		"Provider Request Log",
		"Provisioning Attempt",
		"Provisioning Operation",
		"Hosting Subscription",
		"Hosting Payment Event",
		"Hosting Payment Allocation",
		"Hosting Payment Transaction",
		"Hosting Payment Method",
		"Hosting Payment Gateway",
		"Hosting Refund",
		"Hosting Credit Note",
		"Customer Credit Transaction",
		"Hosting Promo Redemption",
		"Hosting Promo Code",
		"Hosting Invoice Item",
		"Hosting Invoice",
		"Hosting Order Item",
		"Hosting Order",
		"Hosting Customer Contact",
		"Hosting Service",
		"Hosting Product",
		"Hosting Product Group",
		"Hosting Provider Account",
		"Hosting Customer",
		*extra,
	]
	for dt in doctypes:
		try:
			for name in frappe.get_all(dt, pluck="name"):
				frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
		except Exception:
			continue
	SimulatedRegistrarDriver.REGISTRY.clear()
	frappe.db.commit()


def ensure_user(email, first="Phase14"):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": first,
			 "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	try:
		frappe.get_doc("User", email).add_roles("Hosting Customer")
	except Exception:
		pass
	return email


def ensure_customer(user, name="P14 Buyer"):
	existing = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	if existing:
		return existing
	return frappe.get_doc(
		{"doctype": "Hosting Customer", "customer_name": name,
		 "primary_user": user, "status": "Active", "email_verified": 1}
	).insert().name


def ensure_products():
	if not frappe.db.exists("Hosting Product Group", "Phase14 Group"):
		frappe.get_doc({"doctype": "Hosting Product Group",
			"product_group_name": "Phase14 Group"}).insert()
	for name, price in (("Phase14 Small", 10), ("Phase14 Large", 20)):
		if not frappe.db.exists("Hosting Product", name):
			frappe.get_doc({"doctype": "Hosting Product", "product_name": name,
				"product_group": "Phase14 Group", "billing_cycle": "Monthly",
				"price": price, "currency": "USD"}).insert()
	return "Phase14 Small", "Phase14 Large"


def ensure_gateway():
	if frappe.db.exists("Hosting Payment Gateway", "Phase14 Gateway"):
		return "Phase14 Gateway"
	return frappe.get_doc({"doctype": "Hosting Payment Gateway",
		"gateway_name": "Phase14 Gateway", "provider": "Test Gateway",
		"supported_currencies": "USD", "default_currency": "USD",
		"webhook_secret": SECRET, "is_active": 1,
		"max_retries": 3, "retry_backoff_minutes": 30}).insert().name


def ensure_provider_account():
	if frappe.db.exists("Hosting Provider Account", "Phase14 Proxmox"):
		return "Phase14 Proxmox"
	return frappe.get_doc({"doctype": "Hosting Provider Account",
		"provider_name": "Phase14 Proxmox",
		"provider_type": "Proxmox VE"}).insert().name


def sign(raw):
	return hmac.new(SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()


def envelope(event_id, event_type, ref, amount=10.0, currency="USD"):
	return json.dumps({"id": event_id, "type": event_type,
		"payment_reference": ref, "amount": amount, "currency": currency})
