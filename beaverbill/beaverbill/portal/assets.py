"""Phase 10 portal: domains, SSL, backups, addons, and storage for owners."""

import frappe

from beaverbill.beaverbill import addons as addon_engine
from beaverbill.beaverbill import backups as backup_engine
from beaverbill.beaverbill import certificates as cert_engine
from beaverbill.beaverbill import domains as domain_engine
from beaverbill.beaverbill.portal.guard import may_access_customer, own_domain_or_throw, portal_customer, portal_endpoint


def _own_backup(name: str, user=None) -> object:
	doc = frappe.get_doc("Service Backup", name)
	if not may_access_customer(doc.customer, user):
		frappe.throw(f"Backup {name} does not belong to this customer", frappe.PermissionError)
	return doc


@frappe.whitelist()
@portal_endpoint("portal.my_domains", limit=60)
def my_domains() -> dict:
	"""Domains owned by the caller."""
	customer = portal_customer()
	rows = frappe.get_all(
		"Hosting Domain",
		filters={"customer": customer},
		fields=["name", "domain_name", "status", "expiry_date", "auto_renew", "transfer_status"],
		order_by="creation desc",
	)
	return {"domains": rows}


@frappe.whitelist()
@portal_endpoint("portal.domain_detail", limit=60)
def domain_detail(domain: str) -> dict:
	"""Domain detail with DNS records (ownership enforced)."""
	doc = own_domain_or_throw(domain)
	records = frappe.get_all(
		"Hosting DNS Record",
		filters={"domain": doc.name, "status": "Active"},
		fields=["name", "record_type", "host", "value", "ttl", "priority"],
	)
	return {
		"name": doc.name, "domain_name": doc.domain_name, "status": doc.status,
		"expiry_date": str(doc.expiry_date or ""), "auto_renew": doc.auto_renew,
		"nameservers": (doc.nameservers or "").splitlines(),
		"transfer_status": doc.transfer_status, "records": records,
	}


@frappe.whitelist()
@portal_endpoint("portal.dns_add", limit=30)
def dns_add(domain: str, record_type: str, host: str, value: str,
			ttl: int = 3600, priority: int = 0) -> dict:
	"""Add a DNS record on the caller's domain."""
	own_domain_or_throw(domain)
	rec = domain_engine.add_dns_record(domain, record_type, host, value, ttl=int(ttl or 3600),
									   priority=int(priority or 0))
	return {"record": rec.name}


@frappe.whitelist()
@portal_endpoint("portal.dns_remove", limit=30)
def dns_remove(record: str) -> dict:
	"""Deactivate a DNS record on the caller's domain."""
	doc = frappe.get_doc("Hosting DNS Record", record)
	own_domain_or_throw(doc.domain)
	return domain_engine.remove_dns_record(record)


@frappe.whitelist()
@portal_endpoint("portal.my_certificates", limit=60)
def my_certificates() -> dict:
	"""Certificates owned by the caller."""
	customer = portal_customer()
	rows = frappe.get_all(
		"SSL Certificate",
		filters={"customer": customer},
		fields=["name", "domain", "service", "status", "expires_at", "validation_method"],
		order_by="creation desc",
	)
	return {"certificates": rows}


@frappe.whitelist()
@portal_endpoint("portal.request_certificate", limit=10)
def request_certificate(domain: str, service: str | None = None,
						validation_method: str = "DNS") -> dict:
	"""Order a certificate for the caller's domain (and service)."""
	dom = own_domain_or_throw(domain)
	if service:
		from beaverbill.beaverbill.portal.guard import own_service_or_throw

		own_service_or_throw(service)
	return cert_engine.request_certificate(dom.name, dom.customer, service=service,
										   validation_method=validation_method)


@frappe.whitelist()
@portal_endpoint("portal.my_backups", limit=60)
def my_backups(service: str | None = None) -> dict:
	"""Backups for the caller's services, optionally filtered."""
	customer = portal_customer()
	filters = {"customer": customer}
	if service:
		from beaverbill.beaverbill.portal.guard import own_service_or_throw

		own_service_or_throw(service)
		filters["service"] = service
	rows = frappe.get_all(
		"Service Backup",
		filters=filters,
		fields=["name", "service", "status", "started_at", "finished_at", "size_mb", "retain_until"],
		order_by="creation desc",
		limit_page_length=50,
	)
	return {"backups": rows}


@frappe.whitelist()
@portal_endpoint("portal.request_restore", limit=10)
def request_restore(backup: str, service: str) -> dict:
	"""Request a restore of the caller's backup (approval still required)."""
	_own_backup(backup)
	return backup_engine.request_restore(backup, service)


@frappe.whitelist()
@portal_endpoint("portal.restore_status", limit=60)
def restore_status(restore: str) -> dict:
	"""Restore status for the caller's request."""
	doc = frappe.get_doc("Restore Request", restore)
	if not may_access_customer(doc.customer):
		frappe.throw(f"Restore {restore} does not belong to this customer", frappe.PermissionError)
	return {"restore": doc.name, "status": doc.status, "backup": doc.backup,
			"service": doc.service, "completed_at": str(doc.completed_at or "")}


@frappe.whitelist()
@portal_endpoint("portal.my_addons", limit=60)
def my_addons(service: str | None = None) -> dict:
	"""Active addons on the caller's services."""
	customer = portal_customer()
	filters = {"customer": customer}
	if service:
		from beaverbill.beaverbill.portal.guard import own_service_or_throw

		own_service_or_throw(service)
		filters["service"] = service
	rows = frappe.get_all(
		"Service Addon",
		filters=filters,
		fields=["name", "service", "addon", "status", "price", "billing_cycle", "current_period_end"],
		order_by="creation desc",
	)
	return {"addons": rows}


@frappe.whitelist()
@portal_endpoint("portal.order_addon", limit=10)
def order_addon(service: str, addon: str, idempotency_key: str) -> dict:
	"""Order a catalog addon on the caller's service."""
	from beaverbill.beaverbill.portal.guard import own_service_or_throw

	svc = own_service_or_throw(service)
	return addon_engine.provision_addon(svc.name, addon, subscription=svc.subscription,
										idempotency_key=idempotency_key)


@frappe.whitelist()
@portal_endpoint("portal.cancel_addon", limit=10)
def cancel_addon(addon: str, mode: str = "End of Period") -> dict:
	"""Cancel the caller's addon immediately or at period end."""
	doc = frappe.get_doc("Service Addon", addon)
	if not may_access_customer(doc.customer):
		frappe.throw(f"Addon {addon} does not belong to this customer", frappe.PermissionError)
	return addon_engine.cancel_addon(addon, mode=mode)


@frappe.whitelist()
@portal_endpoint("portal.storage_usage", limit=60)
def storage_usage(service: str) -> dict:
	"""Latest storage measurements for the caller's service."""
	from beaverbill.beaverbill.portal.guard import own_service_or_throw

	own_service_or_throw(service)
	rows = frappe.get_all(
		"Service Storage Usage",
		filters={"service": service},
		fields=["measured_at", "used_gb", "quota_gb", "overage_gb", "overage_invoice"],
		order_by="measured_at desc",
		limit_page_length=30,
	)
	return {"service": service, "snapshots": rows}
