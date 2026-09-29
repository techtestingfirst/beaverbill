"""Phase 15 pair reconciliation: compare sources of truth, list mismatches.

Every runner is read-only and caps its detail at 50 rows. `run_all`
aggregates; `run_reconciliation_cycle` additionally raises one
Warning alert per mismatched pair (check name `recon:<pair>`) and
resolves pairs that came back clean.
"""

from __future__ import annotations

import frappe
from frappe.utils import getdate, today

from beaverbill.beaverbill import settings as bb_settings

LIMIT = 50


def _limit() -> int:
	return bb_settings.get_int("recon_batch_limit", LIMIT)


def _overdue_flag_days() -> int:
	return bb_settings.get_int("invoice_overdue_flag_days", 90)


def _out(pair: str, mismatches: list, skipped: str = "") -> dict:
	limit = _limit()
	return {"pair": pair, "count": len(mismatches),
		"mismatches": [str(item)[:200] for item in mismatches[:limit]],
		"skipped": skipped}


def recon_gateway_vs_payments() -> dict:
	bad = []
	for event in frappe.get_all("Hosting Payment Event",
			filters={"status": "Processed"}, fields=["name", "payment"],
			limit_page_length=500):
		if event.payment and not frappe.db.exists("Hosting Payment Transaction",
				event.payment):
			bad.append(f"{event.name}: payment {event.payment} is gone")
	for payment in frappe.get_all("Hosting Payment Transaction",
			filters={"status": "Captured"}, fields=["name", "source_invoice"],
			limit_page_length=500):
		if payment.source_invoice and not frappe.get_all("Hosting Payment Allocation",
				filters={"payment": payment.name}, limit=1):
			bad.append(f"{payment.name}: captured for {payment.source_invoice}"
				" with no allocation")
	return _out("gateway_vs_payments", bad)


def recon_invoices_vs_payments() -> dict:
	bad = []
	for inv in frappe.get_all("Hosting Invoice",
			filters={"status": "Paid"}, fields=["name", "total_amount", "paid_amount"],
			limit_page_length=500):
		if abs(float(inv.total_amount or 0) - float(inv.paid_amount or 0)) > 0.005:
			bad.append(f"{inv.name}: Paid but outstanding "
				f"{float(inv.total_amount or 0) - float(inv.paid_amount or 0):.2f}")
	for inv in frappe.get_all("Hosting Invoice", filters={"status": "Overdue"},
			fields=["name", "due_date"], limit_page_length=500):
		if inv.due_date and (getdate(today()) - getdate(inv.due_date)).days > _overdue_flag_days():
			bad.append(f"{inv.name}: overdue more than {_overdue_flag_days()} days")
	return _out("invoices_vs_payments", bad)


def recon_ledger_vs_balances() -> dict:
	from beaverbill.beaverbill import billing

	return _out("ledger_vs_balances",
		[f"{name}: balance_after differs from running sum"
			for name in billing.ledger_mismatches()])


def recon_services_vs_providers() -> dict:
	from beaverbill.beaverbill.provisioning_drivers import get_provisioning_driver

	bad, skipped = [], 0
	rows = frappe.get_all("Hosting Service",
		filters={"status": ["in", ["Active", "Suspended"]]},
		fields=["name", "status", "subscription", "provider_account"],
		limit_page_length=200)
	for svc in rows:
		if not svc.provider_account:
			skipped += 1
			continue
		driver_type = frappe.db.get_value("Hosting Provider Account",
			svc.provider_account, "provider_type")
		try:
			driver = get_provisioning_driver(driver_type, svc.provider_account)
			if not driver.capabilities().get("describe"):
				skipped += 1
				continue
			remote = driver.describe(svc.subscription or svc.name) or {}
		except Exception:
			skipped += 1
			continue
		remote_state = str(remote.get("status", "")).lower()
		local_state = str(svc.status or "").lower()
		if remote_state and remote_state != local_state and remote_state != "unknown":
			bad.append(f"{svc.name}: local {svc.status} vs remote {remote.get('status')}")
	return _out("services_vs_providers", bad,
		f"{skipped} without provider describe support" if skipped else "")


def recon_ipam_vs_assignments() -> dict:
	bad = []
	rows = frappe.get_all("IPAM IP Address", filters={"status": "Allocated"},
		fields=["name", "ip_address", "allocated_to_doctype", "allocated_to_name"],
		limit_page_length=500)
	for row in rows:
		target = row.allocated_to_doctype
		if not target or not row.allocated_to_name or not frappe.db.exists(
				target, row.allocated_to_name):
			bad.append(f"{row.ip_address}: dangling allocation to "
				f"{target} {row.allocated_to_name}")
			continue
		if target == "Hosting Service":
			state = frappe.db.get_value("Hosting Service", row.allocated_to_name, "status")
			if state in ("Terminated", "Archived"):
				bad.append(f"{row.ip_address}: still allocated to {state} service "
					f"{row.allocated_to_name}")
	return _out("ipam_vs_assignments", bad)


def recon_subscriptions_vs_invoices() -> dict:
	bad = []
	rows = frappe.get_all("Hosting Subscription",
		fields=["name", "status", "last_invoice"], limit_page_length=500)
	for sub in rows:
		if sub.last_invoice and not frappe.db.exists("Hosting Invoice", sub.last_invoice):
			bad.append(f"{sub.name}: renewal invoice {sub.last_invoice} is gone")
		if sub.status == "Terminated":
			alive = frappe.get_all("Hosting Service",
				filters={"subscription": sub.name,
					"status": ["not in", ["Terminated", "Archived"]]},
				pluck="name", limit=5)
			for svc in alive:
				bad.append(f"{sub.name}: terminated but service {svc} is still live")
	return _out("subscriptions_vs_invoices", bad)


def recon_helpdesk_vs_customers() -> dict:
	from beaverbill.beaverbill import helpdesk_sync as bridge

	if not bridge.helpdesk_available():
		return _out("helpdesk_vs_customers", [], "helpdesk not installed")
	bad = []
	known_users = {row.name for row in frappe.get_all("User", fields=["name"],
		limit_page_length=10000)}
	known_customers = {row.primary_user for row in frappe.get_all("Hosting Customer",
		fields=["primary_user"], limit_page_length=10000)}
	for row in frappe.get_all("HD Customer", fields=["name", "email_id"],
			limit_page_length=500):
		if row.email_id and row.email_id not in known_users \
				and row.email_id not in known_customers:
			bad.append(f"HD Customer {row.name}: {row.email_id} has no login")
	for row in frappe.get_all("Hosting Customer",
			fields=["name", "primary_user"], limit_page_length=500):
		if row.primary_user and not frappe.db.exists("HD Customer",
				{"email_id": row.primary_user}):
			bad.append(f"{row.name}: no HD Customer mirror for {row.primary_user}")
	return _out("helpdesk_vs_customers", bad)


def recon_domains_vs_registrar() -> dict:
	from beaverbill.beaverbill.domains import SimulatedRegistrarDriver

	bad, skipped = [], 0
	rows = frappe.get_all("Hosting Domain",
		filters={"status": ["in", ["Active", "Grace Period"]]},
		fields=["name", "domain_name", "expiry_date", "registrar_account"],
		limit_page_length=500)
	for dom in rows:
		registrar = frappe.db.get_value("Domain Registrar Account",
			dom.registrar_account, "registrar") if dom.registrar_account else "Simulated"
		if registrar != "Simulated":
			skipped += 1
			continue
		entry = SimulatedRegistrarDriver.REGISTRY.get((dom.domain_name or "").lower())
		if not entry:
			bad.append(f"{dom.domain_name}: missing from registrar registry")
			continue
		if dom.expiry_date and entry.get("expiry") and abs(
				(getdate(dom.expiry_date) - getdate(entry["expiry"])).days) > 1:
			bad.append(f"{dom.domain_name}: local expiry {dom.expiry_date} vs "
				f"registrar {entry['expiry']}")
	return _out("domains_vs_registrar", bad,
		f"{skipped} on external registrars" if skipped else "")


PAIRS = (
	recon_gateway_vs_payments,
	recon_invoices_vs_payments,
	recon_ledger_vs_balances,
	recon_services_vs_providers,
	recon_ipam_vs_assignments,
	recon_subscriptions_vs_invoices,
	recon_helpdesk_vs_customers,
	recon_domains_vs_registrar,
)


def run_all() -> dict:
	"""Run every pair; a crashing pair reports a mismatch, never raises."""
	pairs = []
	for runner in PAIRS:
		try:
			pairs.append(runner())
		except Exception as exc:
			pairs.append({"pair": runner.__name__, "count": 1,
				"mismatches": [f"runner error: {exc}"], "skipped": ""})
	return {"pairs": pairs, "mismatches": sum(pair["count"] for pair in pairs)}


def run_reconciliation_cycle() -> dict:
	"""Scheduler entry: reconcile, then alert on mismatched pairs."""
	from beaverbill.beaverbill import monitoring

	report = run_all()
	results = [{"check": f"recon:{pair['pair']}",
		"status": "warn" if pair["count"] else "ok",
		"count": pair["count"],
		"detail": "; ".join(pair["mismatches"][:3]) or pair.get("skipped", "")}
		for pair in report["pairs"]]
	monitoring.raise_alerts(results)
	monitoring.resolve_alerts(results)
	return {"pairs": len(report["pairs"]), "mismatches": report["mismatches"],
		"failing": [row["check"] for row in results if row["status"] != "ok"]}
