"""Phase 9 certificate engine: validation, installation, renewal, monitoring."""

import secrets

import frappe
from frappe.utils import add_days, add_months, date_diff, getdate, now_datetime, today

from beaverbill.beaverbill.notifications import notify, require_staff

CERT_VALIDITY_DAYS = 90
EXPIRY_WARN_DAYS = 30
STALE_VALIDATION_DAYS = 7

# Fault injection for tests: {"validate": msg, "renew": msg}
CERT_FAULTS: dict = {}


def _token() -> str:
	return secrets.token_hex(16)


@frappe.whitelist()
def request_certificate(domain: str, customer: str, service: str | None = None,
						validation_method: str = "DNS") -> dict:
	"""Order a certificate; validation material is issued, not yet checked."""
	dom = frappe.get_doc("Hosting Domain", domain)
	if dom.status in ("Cancelled", "Terminated"):
		frappe.throw(f"Certificates cannot be ordered for a {dom.status} domain", frappe.ValidationError)
	if service:
		svc_customer = frappe.db.get_value("Hosting Service", service, "customer")
		if svc_customer and svc_customer != dom.customer:
			frappe.throw("Installation target belongs to a different customer", frappe.ValidationError)
	cert = frappe.get_doc(
		{
			"doctype": "SSL Certificate",
			"domain": dom.name,
			"customer": customer or dom.customer,
			"service": service,
			"status": "Pending Validation",
			"validation_method": validation_method or "DNS",
			"validation_token": _token(),
			"auto_renew": 1,
		}
	).insert()
	if validation_method == "DNS":
		notify(cert.customer, f"Certificate validation pending for {dom.domain_name}", f"Add a TXT record for _acme-challenge with value {cert.validation_token}, then validate.", "SSL Certificate", cert.name)
	return {"certificate": cert.name, "status": cert.status, "validation_token": cert.validation_token}


def _check_dns_challenge(cert) -> bool:
	"""DNS validation passes when the challenge TXT record exists locally."""
	dom = frappe.get_doc("Hosting Domain", cert.domain)
	rows = frappe.get_all(
		"Hosting DNS Record",
		filters={
			"domain": dom.name,
			"record_type": "TXT",
			"host": "_acme-challenge",
			"value": cert.validation_token,
			"status": "Active",
		},
		limit=1,
	)
	return bool(rows)


@frappe.whitelist()
def validate_certificate(name: str) -> dict:
	"""Run validation; success activates the certificate for 90 days."""
	cert = frappe.get_doc("SSL Certificate", name)
	if cert.status not in ("Pending Validation", "Renewal Pending", "Failed"):
		frappe.throw(f"Certificate {cert.status} needs no validation", frappe.ValidationError)
	if CERT_FAULTS.get("validate"):
		return _fail_validation(cert, CERT_FAULTS["validate"])
	ok = _check_dns_challenge(cert) if cert.validation_method == "DNS" else True
	if not ok:
		return _fail_validation(cert, "Challenge record not found; publish it and retry")
	cert.status = "Active"
	cert.issued_at = now_datetime()
	cert.expires_at = add_days(getdate(today()), CERT_VALIDITY_DAYS)
	cert.failure_reason = None
	cert.last_checked_at = now_datetime()
	cert.save()
	dom = frappe.db.get_value("Hosting Domain", cert.domain, "domain_name")
	notify(cert.customer, f"Certificate active for {dom}", f"Your certificate is valid until {cert.expires_at}.", "SSL Certificate", cert.name)
	return {"certificate": cert.name, "status": cert.status}


def _fail_validation(cert, reason: str) -> dict:
	cert.status = "Failed"
	cert.failure_reason = reason[:1000]
	cert.last_checked_at = now_datetime()
	cert.save()
	notify(cert.customer, "Certificate validation failed", f"{reason} Fix it and revalidate.", "SSL Certificate", cert.name)
	return {"certificate": cert.name, "status": cert.status, "error": reason}


@frappe.whitelist()
def install_certificate(name: str, service: str) -> dict:
	"""Point the certificate at its installation target service."""
	require_staff()
	cert = frappe.get_doc("SSL Certificate", name)
	if cert.status != "Active":
		frappe.throw(f"Only Active certificates can be installed, not {cert.status}", frappe.ValidationError)
	svc_customer = frappe.db.get_value("Hosting Service", service, "customer")
	if svc_customer != cert.customer:
		frappe.throw("Installation target belongs to a different customer", frappe.ValidationError)
	cert.service = service
	cert.save()
	return {"certificate": cert.name, "service": service}


@frappe.whitelist()
def renew_certificate(name: str) -> dict:
	"""Renew: fresh token, immediate validation attempt, extended validity."""
	cert = frappe.get_doc("SSL Certificate", name)
	if cert.status not in ("Active", "Renewal Pending", "Expired"):
		frappe.throw(f"Certificate {cert.status} cannot be renewed", frappe.ValidationError)
	if CERT_FAULTS.get("renew"):
		cert.status = "Failed"
		cert.failure_reason = f"Renewal failed: {CERT_FAULTS['renew']}"[:1000]
		cert.save()
		notify(cert.customer, "Certificate renewal failed", f"{CERT_FAULTS['renew']} Staff will retry.", "SSL Certificate", cert.name)
		return {"certificate": cert.name, "status": cert.status, "error": CERT_FAULTS["renew"]}
	cert.renewal_idempotency_key = f"{cert.name}-renew-{cert.expires_at}"
	cert.validation_token = _token()
	cert.status = "Renewal Pending"
	cert.save()
	return validate_certificate(cert.name)


def monitor_certificates(as_of=None) -> dict:
	"""Daily job: expiry watch, auto-renewal, stale-validation cleanup."""
	day = getdate(as_of) if as_of else getdate(today())
	ran = {"renewed": 0, "failed": 0, "expired": 0, "stale": 0}
	for row in frappe.get_all("SSL Certificate", filters={"status": ("in", ["Active", "Renewal Pending"])}, fields=["name"]):
		cert = frappe.get_doc("SSL Certificate", row.name)
		cert.last_checked_at = now_datetime()
		cert.save(ignore_permissions=True)
		if not cert.expires_at:
			continue
		days_left = date_diff(getdate(cert.expires_at), day)
		if days_left < 0:
			cert.status = "Expired"
			cert.save(ignore_permissions=True)
			ran["expired"] += 1
			notify(cert.customer, "Certificate expired", "Renew it to restore HTTPS.", "SSL Certificate", cert.name)
		elif days_left <= EXPIRY_WARN_DAYS and cert.auto_renew and cert.status == "Active":
			out = renew_certificate(cert.name)
			if out.get("status") == "Active":
				ran["renewed"] += 1
			else:
				ran["failed"] += 1
		frappe.db.commit()
	cutoff = add_days(day, -STALE_VALIDATION_DAYS)
	for row in frappe.get_all("SSL Certificate", filters={"status": "Pending Validation"}, fields=["name", "creation"]):
		if getdate(row.creation) < cutoff:
			cert = frappe.get_doc("SSL Certificate", row.name)
			_fail_validation(cert, "Validation window expired; request a fresh challenge")
			ran["stale"] += 1
			frappe.db.commit()
	return ran
