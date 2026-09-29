"""Phase 15 health checks: one read-only check per monitored area.

Each check returns {"check", "status", "count", "detail"} where status
is ok, warn, or fail. `run_checks` never raises; a crashing check
reports fail with the error as detail. Alerts are deduplicated by
check name in Monitoring Alert, and newly failing checks mail
System Managers best-effort.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime, today

from beaverbill.beaverbill import settings as bb_settings

STATUSES = ("ok", "warn", "fail")


def _expiring_warn_days() -> int:
	return bb_settings.get_int("expiring_warn_days", 30)


def _expiring_urgent_days() -> int:
	return bb_settings.get_int("expiring_urgent_days", 7)


def _ip_low_threshold() -> float:
	return bb_settings.get_float("ip_low_threshold_pct", 10) / 100.0


def _since(hours: int) -> str:
	return str(add_to_date(now_datetime(), hours=-hours))


def _result(check: str, status: str, count: int, detail: str = "") -> dict:
	return {"check": check, "status": status, "count": int(count),
		"detail": (detail or "")[:500]}


def _level(count: int, warn_at: int, fail_at: int) -> str:
	if count >= fail_at:
		return "fail"
	if count >= warn_at:
		return "warn"
	return "ok"


def check_failed_payments() -> dict:
	rows = frappe.get_all("Hosting Payment Transaction",
		filters={"status": "Failed", "modified": [">=", _since(24)]}, pluck="name")
	return _result("mon:failed_payments", _level(len(rows), 1, 5), len(rows),
		f"failed in 24h: {', '.join(rows[:5])}" if rows else "")


def check_unprocessed_webhooks() -> dict:
	pending = frappe.get_all("Hosting Payment Event",
		filters={"status": ["in", ["Received", "Validated"]],
			"modified": ["<", _since(0.25)]}, pluck="name")
	failed = frappe.get_all("Hosting Payment Event",
		filters={"status": "Failed", "modified": [">=", _since(24)]}, pluck="name")
	count = len(pending) + len(failed)
	status = "fail" if failed or len(pending) > 10 else _level(count, 1, 11)
	return _result("mon:unprocessed_webhooks", status, count,
		f"pending={len(pending)} failed={len(failed)}")


def check_renewal_failures() -> dict:
	rows = frappe.get_all("Hosting Subscription",
		filters={"status": ["in", ["Payment Failed", "Grace Period"]]}, pluck="name")
	return _result("mon:renewal_failures", _level(len(rows), 1, 10), len(rows),
		f"stuck: {', '.join(rows[:5])}" if rows else "")


def check_provisioning() -> dict:
	failed = frappe.get_all("Provisioning Operation",
		filters={"status": "Failed", "modified": [">=", _since(24)]}, pluck="name")
	stuck = frappe.get_all("Provisioning Operation",
		filters={"status": ["in", ["Queued", "Running"]],
			"modified": ["<", _since(2)]}, pluck="name")
	status = "fail" if stuck or len(failed) >= 5 else _level(len(failed), 1, 5)
	return _result("mon:provisioning", status, len(failed) + len(stuck),
		f"failed24h={len(failed)} stuck={len(stuck)}")


def check_provider_errors() -> dict:
	rows = frappe.get_all("Provider Request Log",
		filters={"logged_at": [">=", _since(24)]},
		fields=["name", "error_type"], limit_page_length=500)
	bad = [row.name for row in rows if row.error_type]
	return _result("mon:provider_errors", _level(len(bad), 1, 20), len(bad),
		f"errors in 24h: {', '.join(bad[:5])}" if bad else "")


def check_ip_exhaustion() -> dict:
	subnets = frappe.get_all("IPAM Subnet", pluck="name")
	empty, low = [], []
	for subnet in subnets:
		total = frappe.db.count("IPAM IP Address", {"subnet": subnet})
		free = frappe.db.count("IPAM IP Address",
			{"subnet": subnet, "status": "Available"})
		if not total:
			continue
		if free == 0:
			empty.append(subnet)
		elif free / total < _ip_low_threshold():
			low.append(subnet)
	status = "fail" if empty else _level(len(low), 1, 10 ** 9)
	return _result("mon:ip_exhaustion", status, len(empty) + len(low),
		f"empty={empty[:5]} low={low[:5]}" if (empty or low) else "")


def check_expiring_domains() -> dict:
	rows = frappe.get_all("Hosting Domain", filters={"status": "Active"},
		fields=["name", "expiry_date"], limit_page_length=500)
	soon = [r.name for r in rows if r.expiry_date
		and getdate(r.expiry_date) <= add_days(getdate(today()), _expiring_warn_days())]
	urgent = [r.name for r in rows if r.expiry_date
		and getdate(r.expiry_date) <= add_days(getdate(today()), _expiring_urgent_days())]
	status = "fail" if urgent else _level(len(soon), 1, 10 ** 9)
	return _result("mon:expiring_domains", status, len(soon),
		f"urgent={urgent[:5]}" if urgent else (f"within30d={len(soon)}" if soon else ""))


def check_expiring_certificates() -> dict:
	rows = frappe.get_all("SSL Certificate",
		filters={"status": ["not in", ["Expired", "Revoked", "Failed"]]},
		fields=["name", "expires_at"], limit_page_length=500)
	soon = [r.name for r in rows if r.expires_at
		and getdate(r.expires_at) <= add_days(getdate(today()), _expiring_warn_days())]
	urgent = [r.name for r in rows if r.expires_at
		and getdate(r.expires_at) <= add_days(getdate(today()), _expiring_urgent_days())]
	status = "fail" if urgent else _level(len(soon), 1, 10 ** 9)
	return _result("mon:expiring_certificates", status, len(soon),
		f"urgent={urgent[:5]}" if urgent else (f"within30d={len(soon)}" if soon else ""))


def check_backup_failures() -> dict:
	rows = frappe.get_all("Service Backup",
		filters={"status": "Failed", "modified": [">=", _since(24)]}, pluck="name")
	return _result("mon:backup_failures", _level(len(rows), 1, 5), len(rows),
		f"failed in 24h: {', '.join(rows[:5])}" if rows else "")


def check_email_failures() -> dict:
	if not frappe.db.exists("DocType", "Email Queue"):
		return _result("mon:email_failures", "ok", 0, "Email Queue not present")
	rows = frappe.get_all("Email Queue",
		filters={"status": "Error", "modified": [">=", _since(24)]}, pluck="name")
	return _result("mon:email_failures", _level(len(rows), 1, 10), len(rows),
		f"errors in 24h: {len(rows)}" if rows else "")


def check_helpdesk_sync() -> dict:
	failed, pending = 0, 0
	helpdesk = ""
	try:
		from beaverbill.beaverbill import helpdesk_sync as bridge

		if bridge.helpdesk_available():
			failed = len(bridge.sync_failures().get("failures", []))
			pending = frappe.db.count("Helpdesk Sync Log", {"status": "Pending"})
		else:
			helpdesk = "helpdesk not installed"
	except Exception as exc:
		return _result("mon:helpdesk_sync", "fail", 0, f"check error: {exc}")
	status = "fail" if failed >= 10 else _level(failed + (pending > 50), 1, 10)
	return _result("mon:helpdesk_sync", status, failed,
		helpdesk or f"failed={failed} pending={pending}")


def check_orphaned_cleanup() -> dict:
	stale = frappe.get_all("Resource Cleanup Task",
		filters={"status": "Pending", "modified": ["<", _since(24)]}, pluck="name")
	broken = frappe.get_all("Resource Cleanup Task",
		filters={"status": "Failed"}, pluck="name")
	count = len(stale) + len(broken)
	status = "fail" if stale else _level(count, 1, 10 ** 9)
	return _result("mon:orphaned_cleanup", status, count,
		f"stale={len(stale)} failed={len(broken)}" if count else "")


def check_ledger() -> dict:
	from beaverbill.beaverbill import billing

	bad = billing.ledger_mismatches()
	overdue = frappe.db.count("Hosting Invoice", {"status": "Overdue"})
	status = "fail" if bad else _level(overdue, 1, 10 ** 9)
	return _result("mon:ledger", status, len(bad) + overdue,
		f"ledger_mismatches={len(bad)} overdue={overdue}" if (bad or overdue) else "")


CHECKS = (
	check_failed_payments,
	check_unprocessed_webhooks,
	check_renewal_failures,
	check_provisioning,
	check_provider_errors,
	check_ip_exhaustion,
	check_expiring_domains,
	check_expiring_certificates,
	check_backup_failures,
	check_email_failures,
	check_helpdesk_sync,
	check_orphaned_cleanup,
	check_ledger,
)


def run_checks() -> list:
	"""Run every check; a crashing check reports fail, never raises."""
	results = []
	for check in CHECKS:
		try:
			out = check()
			if out.get("status") not in STATUSES:
				out["status"] = "fail"
			results.append(out)
		except Exception as exc:
			results.append(_result(f"mon:{check.__name__}", "fail", 0,
				f"check error: {exc}"))
	return results


def _admin_emails() -> list:
	try:
		return frappe.get_all("User",
			filters={"user_type": "System User", "enabled": 1}, pluck="name")
	except Exception:
		return []


def _notify_admins(check: str, detail: str) -> None:
	recipients = [email for email in _admin_emails()
		if "System Manager" in (frappe.get_roles(email) or [])][:5]
	if not recipients:
		return
	try:
		frappe.sendmail(recipients=recipients,
			subject=f"[BeaverBill] {check} is failing",
			message=f"Check {check} reported a failure:\n\n{detail}")
	except Exception:
		pass


def raise_alerts(results: list) -> list:
	"""Upsert one open Monitoring Alert per non-ok check. Returns names."""
	touched = []
	for row in results:
		if row.get("status") == "ok":
			continue
		name = frappe.db.get_value("Monitoring Alert",
			{"check": row["check"], "status": "Open"}, "name")
		severity = "Critical" if row["status"] == "fail" else "Warning"
		if name:
			doc = frappe.get_doc("Monitoring Alert", name)
			doc.severity = severity
			doc.detail = row.get("detail", "")
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.get_doc({"doctype": "Monitoring Alert",
				"check": row["check"], "status": "Open", "severity": severity,
				"detail": row.get("detail", "")}).insert(ignore_permissions=True)
			if row["status"] == "fail":
				_notify_admins(row["check"], row.get("detail", ""))
		touched.append(doc.name)
	return touched


def resolve_alerts(results: list) -> int:
	"""Resolve open alerts whose checks now report ok. Returns count."""
	healthy = {row["check"] for row in results if row.get("status") == "ok"}
	count = 0
	for name in frappe.get_all("Monitoring Alert",
			filters={"status": "Open"}, pluck="name"):
		check = frappe.db.get_value("Monitoring Alert", name, "check")
		if check in healthy:
			doc = frappe.get_doc("Monitoring Alert", name)
			doc.status = "Resolved"
			doc.save(ignore_permissions=True)
			count += 1
	return count


def run_monitoring_cycle() -> dict:
	"""Scheduler entry: check, alert, resolve. Returns the summary."""
	results = run_checks()
	alerts = raise_alerts(results)
	resolved = resolve_alerts(results)
	failing = [row["check"] for row in results if row["status"] != "ok"]
	return {"checks": len(results), "failing": failing,
		"alerts": len(alerts), "resolved": resolved}


@frappe.whitelist()
def health_dashboard() -> dict:
	"""Staff-only: live check results plus open alerts."""
	from beaverbill.beaverbill.portal.guard import is_staff

	if not is_staff():
		frappe.throw("Only staff may view the health dashboard", frappe.PermissionError)
	alerts = frappe.get_all("Monitoring Alert", filters={"status": "Open"},
		fields=["check", "severity", "detail", "first_seen", "last_seen"],
		order_by="last_seen desc", limit_page_length=100)
	return {"checks": run_checks(), "open_alerts": alerts}
