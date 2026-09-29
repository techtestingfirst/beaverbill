"""Phase 9 addon engine: product/price/order/subscription/fulfilment/renew/cancel/fail.

Every Service Addon carries a frozen product snapshot and an
idempotency key. Fulfilment failures reuse Phase 8 cleanup tasks.
"""

import json

import frappe
from frappe.utils import add_months, getdate, now_datetime, today

from beaverbill.beaverbill import billing
from beaverbill.beaverbill.notifications import billable_customer, notify, require_staff

CYCLE_MONTHS = {
	"Monthly": 1,
	"Quarterly": 3,
	"Semi-Annually": 6,
	"Annually": 12,
	"Biennially": 24,
	"Triennially": 36,
}

# Fault injection for tests: {"fulfill": msg}
ADDON_FAULTS: dict = {}


def _snapshot(addon_name: str) -> dict:
	row = frappe.get_doc("Hosting Product Addon", addon_name)
	product = frappe.get_doc("Hosting Product", row.product) if row.product else None
	return {
		"addon": row.name,
		"addon_name": row.addon_name,
		"product": row.product,
		"price": float(row.price or 0),
		"currency": product.currency if product else "USD",
		"billing_cycle": product.billing_cycle if product else "Monthly",
	}


@frappe.whitelist()
def provision_addon(service: str, addon: str, subscription: str | None = None,
					idempotency_key: str | None = None) -> dict:
	"""Order an addon: snapshot the catalog row, then fulfil exactly once."""
	svc = frappe.get_doc("Hosting Service", service)
	key = idempotency_key or f"addon-{service}-{addon}"
	existing = frappe.db.get_value("Service Addon", {"idempotency_key": key}, "name")
	if existing:
		doc = frappe.get_doc("Service Addon", existing)
		return {"addon": doc.name, "status": doc.status, "duplicate_request": True}
	snap = _snapshot(addon)
	row = frappe.get_doc(
		{
			"doctype": "Service Addon",
			"service": service,
			"subscription": subscription or svc.subscription,
			"customer": svc.customer,
			"addon": addon,
			"status": "Pending",
			"price": snap["price"],
			"billing_cycle": snap["billing_cycle"],
			"product_snapshot": json.dumps(snap, default=str),
			"current_period_end": add_months(getdate(today()), CYCLE_MONTHS.get(snap["billing_cycle"], 1)),
			"idempotency_key": key,
		}
	).insert()
	return _fulfil(row.name)


def _fulfil(name: str) -> dict:
	row = frappe.get_doc("Service Addon", name)
	if ADDON_FAULTS.get("fulfill"):
		row.status = "Failed"
		row.failure_reason = ADDON_FAULTS["fulfill"][:1000]
		row.save()
		frappe.get_doc(
			{
				"doctype": "Resource Cleanup Task",
				"service": row.service,
				"task_type": "Manual Check",
				"status": "Pending",
				"details": f"Addon fulfilment failed: {ADDON_FAULTS['fulfill']}"[:500],
			}
		).insert(ignore_permissions=True)
		notify(row.customer, "Addon fulfilment failed", f"{ADDON_FAULTS['fulfill']} Staff can retry.", "Service Addon", row.name)
		return {"addon": row.name, "status": row.status, "error": ADDON_FAULTS["fulfill"]}
	row.status = "Active"
	row.fulfilment_detail = f"Fulfilled at {now_datetime()} against snapshot {row.addon}"
	row.failure_reason = None
	row.save()
	notify(row.customer, "Addon active", f"Addon {row.addon} is active on service {row.service}.", "Service Addon", row.name)
	return {"addon": row.name, "status": row.status}


@frappe.whitelist()
def retry_addon(name: str) -> dict:
	"""Staff action: re-run fulfilment for a Failed addon."""
	require_staff()
	row = frappe.get_doc("Service Addon", name)
	if row.status != "Failed":
		frappe.throw(f"Only Failed addons can be retried, not {row.status}", frappe.ValidationError)
	row.status = "Pending"
	row.save()
	return _fulfil(row.name)


def renew_addon(name: str) -> dict:
	"""Renew an addon: invoice first (idempotent), extend on payment."""
	row = frappe.get_doc("Service Addon", name)
	if row.status != "Active":
		frappe.throw(f"Only Active addons renew, not {row.status}", frappe.ValidationError)
	snap = json.loads(row.product_snapshot or "{}")
	invoice = billing.issue_invoice(
		billable_customer(row.customer),
		[{
			"description": f"Addon renewal {snap.get('addon_name') or row.addon}",
			"product": snap.get("product"),
			"qty": 1,
			"unit_price": float(row.price or 0),
			"line_total": float(row.price or 0),
			"billing_cycle": row.billing_cycle,
		}],
		currency=snap.get("currency") or "USD",
		idempotency_key=f"{row.idempotency_key}-renew-{row.current_period_end}",
	)
	row.renewal_invoice = invoice.name
	if invoice.status == "Paid":
		months = CYCLE_MONTHS.get(row.billing_cycle or "Monthly", 1)
		base = max(getdate(row.current_period_end or today()), getdate(today()))
		row.current_period_end = add_months(base, months)
		row.renewal_invoice = None
	row.save(ignore_permissions=True)
	return {"addon": row.name, "invoice": invoice.name, "paid": invoice.status == "Paid"}


def process_addon_renewals(as_of=None) -> dict:
	"""Daily job: invoice due addons, extend paid ones, close end-of-period cancels."""
	day = getdate(as_of) if as_of else getdate(today())
	ran = {"invoiced": 0, "extended": 0, "cancelled": 0}
	for row in frappe.get_all("Service Addon", filters={"status": ("in", ["Active", "Cancellation Pending"])}, fields=["name", "status", "current_period_end"]):
		doc = frappe.get_doc("Service Addon", row.name)
		if doc.status == "Cancellation Pending" and getdate(doc.current_period_end or day) <= day:
			doc.status = "Cancelled"
			doc.save(ignore_permissions=True)
			ran["cancelled"] += 1
			notify(doc.customer, "Addon cancelled", f"Addon {doc.addon} is cancelled.", "Service Addon", doc.name)
		elif doc.status == "Active" and doc.current_period_end and getdate(doc.current_period_end) <= day:
			out = renew_addon(doc.name)
			ran["invoiced"] += 1
			if out.get("paid"):
				ran["extended"] += 1
		frappe.db.commit()
	return ran


@frappe.whitelist()
def cancel_addon(name: str, mode: str = "End of Period") -> dict:
	"""Cancel immediately or at the end of the current period."""
	row = frappe.get_doc("Service Addon", name)
	if row.status not in ("Active", "Suspended", "Pending"):
		frappe.throw(f"Addon {row.status} cannot be cancelled", frappe.ValidationError)
	row.status = "Cancelled" if mode == "Immediate" else "Cancellation Pending"
	row.save()
	return {"addon": row.name, "status": row.status}


def sync_addons_for_service(service: str, service_status: str) -> list:
	"""Mirror service suspension/termination onto its addons (best effort)."""
	target = {"Suspended": "Suspended", "Terminated": "Cancelled", "Active": "Active"}.get(service_status)
	if not target:
		return []
	updated = []
	for name in frappe.get_all("Service Addon", filters={"service": service}, pluck="name"):
		row = frappe.get_doc("Service Addon", name)
		if row.status == target or row.status in ("Cancelled",):
			continue
		# Suspended addons resume only back to Active.
		if row.status == "Suspended" and target == "Active":
			row.status = "Active"
		elif row.status in ("Active", "Suspended") and target in ("Suspended", "Cancelled"):
			row.status = target
		else:
			continue
		try:
			row.save(ignore_permissions=True)
			updated.append(name)
		except Exception:
			continue
	return updated
