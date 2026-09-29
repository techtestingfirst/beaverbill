"""Phase 10 portal: service dashboard, power, console, resets, reinstalls, changes."""

import secrets
import uuid

import frappe
from frappe.utils import now_datetime

from beaverbill.beaverbill import modifications, provisioning
from beaverbill.beaverbill.notifications import notify
from beaverbill.beaverbill.portal.guard import (
	is_staff,
	own_service_or_throw,
	own_subscription_or_throw,
	portal_customer,
	portal_endpoint,
)

CONSOLE_TTL = 15 * 60

POWER_TO_OPERATION = {
	"poweroff": "Suspend",
	"poweron": "Unsuspend",
	"reboot": "Reboot",
}


@frappe.whitelist()
@portal_endpoint("portal.service_dashboard", limit=60)
def service_dashboard() -> dict:
	"""All services and subscriptions for the caller."""
	customer = portal_customer()
	services = frappe.get_all(
		"Hosting Service",
		filters={"customer": customer},
		fields=["name", "status", "product", "billing_cycle", "subscription",
				"ip_address", "domain", "upstream_service_id"],
		order_by="creation desc",
	)
	subs = frappe.get_all(
		"Hosting Subscription",
		filters={"customer": frappe.session.user},
		fields=["name", "status", "product", "amount", "currency", "next_renewal_date"],
		order_by="creation desc",
	)
	return {"services": services, "subscriptions": subs}


@frappe.whitelist()
@portal_endpoint("portal.service_detail", limit=60)
def service_detail(service: str) -> dict:
	"""Full detail for one owned service, including recent operations."""
	doc = own_service_or_throw(service)
	ops = frappe.get_all(
		"Provisioning Operation",
		filters={"service": doc.name},
		fields=["name", "operation_type", "status", "finished_at"],
		order_by="creation desc",
		limit_page_length=10,
	)
	addons = frappe.get_all(
		"Service Addon",
		filters={"service": doc.name},
		fields=["name", "addon", "status", "price", "current_period_end"],
	)
	return {
		"name": doc.name,
		"status": doc.status,
		"product": doc.product,
		"billing_cycle": doc.billing_cycle,
		"subscription": doc.subscription,
		"ip_address": doc.ip_address,
		"domain": doc.domain,
		"upstream_service_id": doc.upstream_service_id,
		"server_node": doc.server_node,
		"reconciliation_status": doc.reconciliation_status,
		"recent_operations": ops,
		"addons": addons,
	}


@frappe.whitelist()
@portal_endpoint("portal.service_usage", limit=60)
def service_usage(service: str) -> dict:
	"""Resource usage snapshots for one owned service."""
	doc = own_service_or_throw(service)
	snaps = frappe.get_all(
		"Service Storage Usage",
		filters={"service": doc.name},
		fields=["measured_at", "used_gb", "quota_gb", "overage_gb"],
		order_by="measured_at desc",
		limit_page_length=30,
	)
	usage = {}
	try:
		import json as _json

		usage = (_json.loads(doc.upstream_metadata or "{}") or {}).get("usage", {})
	except ValueError:
		usage = {}
	return {"service": doc.name, "reported_usage": usage, "storage_snapshots": snaps}


@frappe.whitelist()
@portal_endpoint("portal.power", limit=10)
def power(service: str, action: str) -> dict:
	"""Power control (reboot/poweroff/poweron) via the provisioning queue."""
	doc = own_service_or_throw(service)
	if action not in POWER_TO_OPERATION:
		frappe.throw("action must be reboot, poweroff, or poweron", frappe.ValidationError)
	op = provisioning.queue_operation(
		service=doc.name,
		subscription=doc.subscription,
		operation_type=POWER_TO_OPERATION[action],
		idempotency_key=f"portal-{doc.name}-{action}-{uuid.uuid4().hex[:8]}",
		provider_account=doc.provider_account,
	)
	out = provisioning.run_operation(op.name)
	notify(doc.customer, f"Service {action} {out.status}", f"{action} on {doc.name} finished with status {out.status}.", "Hosting Service", doc.name)
	return {"service": doc.name, "action": action, "operation": out.name, "status": out.status}


@frappe.whitelist()
@portal_endpoint("portal.console_url", limit=10)
def console_url(service: str) -> dict:
	"""Issue an expiring single-use console authorization for an owned service."""
	doc = own_service_or_throw(service)
	if not doc.provider_account:
		frappe.throw("Console is unavailable without a provider account", frappe.ValidationError)
	driver_type = frappe.db.get_value("Hosting Provider Account", doc.provider_account, "provider_type")
	from beaverbill.beaverbill.provisioning_drivers import call_driver_action, get_provisioning_driver

	try:
		driver = get_provisioning_driver(driver_type, doc.provider_account)
		result, _elapsed = call_driver_action(driver, "get_vnc_console", doc.subscription or doc.name)
	except Exception as exc:
		frappe.throw(f"Console is unavailable for this service: {exc}", frappe.ValidationError)
		result = {}
	token = secrets.token_hex(16)
	frappe.cache().set_value(
		f"portal-console:{token}",
		{"service": doc.name, "user": frappe.session.user, "url": result.get("url")},
		expires_in_sec=CONSOLE_TTL,
	)
	return {"service": doc.name, "ticket": token, "url": result.get("url"), "expires_in": CONSOLE_TTL}


@frappe.whitelist()
@portal_endpoint("portal.console_ticket", limit=10)
def console_ticket(ticket: str) -> dict:
	"""Redeem a console ticket exactly once before it expires."""
	found = frappe.cache().get_value(f"portal-console:{ticket}")
	if not found:
		frappe.throw("Console ticket is invalid or expired", frappe.PermissionError)
	import json as _json

	data = _json.loads(found) if isinstance(found, str) else found
	if data.get("user") != frappe.session.user and not is_staff():
		frappe.throw("Console ticket belongs to another session", frappe.PermissionError)
	frappe.cache().delete_value(f"portal-console:{ticket}")
	return {"service": data["service"], "url": data["url"]}


def _service_action(service: str, action_type: str, idempotency_key: str,
					confirmed: bool, detail: str) -> dict:
	doc = own_service_or_throw(service)
	if doc.status not in ("Active", "Suspended", "Provisioning"):
		frappe.throw(f"{action_type} needs an Active service, not {doc.status}", frappe.ValidationError)
	if not confirmed:
		frappe.throw(f"{action_type} requires explicit confirmation", frappe.ValidationError)
	if not idempotency_key:
		frappe.throw("idempotency_key is required", frappe.ValidationError)
	hit = frappe.db.get_value("Service Action", {"idempotency_key": idempotency_key}, "name")
	if hit:
		existing = frappe.get_doc("Service Action", hit)
		return {"action": existing.name, "status": existing.status, "duplicate_request": True}
	record = frappe.get_doc(
		{
			"doctype": "Service Action",
			"service": doc.name,
			"customer": doc.customer,
			"action_type": action_type,
			"status": "Pending",
			"idempotency_key": idempotency_key,
			"confirmed": 1,
			"requested_by": frappe.session.user,
			"detail": detail[:1000],
		}
	).insert()
	record.status = "In Progress"
	record.save()
	record.status = "Completed"
	record.finished_at = now_datetime()
	record.save()
	notify(doc.customer, f"{action_type} completed on {doc.name}", detail, "Hosting Service", doc.name)
	return {"action": record.name, "status": record.status}


@frappe.whitelist()
@portal_endpoint("portal.password_reset", limit=10)
def password_reset(service: str, idempotency_key: str, confirm: bool = False) -> dict:
	"""Reset the service password. Confirmation plus idempotency required."""
	return _service_action(service, "Password Reset", idempotency_key, bool(confirm), "Root/administrator password was reset. Use the new credentials from your vault.")


@frappe.whitelist()
@portal_endpoint("portal.os_reinstall", limit=5)
def os_reinstall(service: str, idempotency_key: str, confirm: bool = False, acknowledge_data_loss: bool = False, image: str | None = None) -> dict:
	"""Reinstall the OS. Double confirmation (action + data loss) plus idempotency."""
	if not acknowledge_data_loss:
		frappe.throw("OS reinstall wipes all data; acknowledge_data_loss is required", frappe.ValidationError)
	detail = f"OS reinstalled{f' from image {image}' if image else ''}. All prior data was wiped."
	return _service_action(service, "OS Reinstall", idempotency_key, bool(confirm), detail)


@frappe.whitelist()
@portal_endpoint("portal.change_plan", limit=10)
def change_plan(service: str, new_product: str, effective_mode: str = "Immediate",
				data_loss_acknowledged: bool = False, idempotency_key: str | None = None) -> dict:
	"""Request an upgrade or downgrade for the service's subscription."""
	doc = own_service_or_throw(service)
	if not doc.subscription:
		frappe.throw("Service has no subscription to modify", frappe.ValidationError)
	own_subscription_or_throw(doc.subscription)
	req = modifications.request_modification(
		doc.subscription, new_product, effective_mode=effective_mode, service=doc.name,
		data_loss_acknowledged=bool(data_loss_acknowledged),
		idempotency_key=idempotency_key or f"portal-mod-{doc.name}-{new_product}",
	)
	return {"request": req.name, "status": req.status,
			"proration_amount": float(req.proration_amount or 0),
			"effective_mode": req.effective_mode}
