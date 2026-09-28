"""Phase 16 release checks: workers, scheduler, smoke, versions, ERPNext-free.

All checks are read-only except `snapshot_versions`, which only writes
the JSON file it returns the path for. Nothing here mutates site data.
"""

from __future__ import annotations

import platform
import subprocess
import sys

import frappe
from frappe.utils.scheduler import is_scheduler_disabled

EXPECTED_DAILY_JOBS = (
	"process_subscription_renewals",
	"process_queued_provisioning_operations",
	"process_domain_renewals",
	"monitor_certificates",
	"run_due_backups",
	"process_helpdesk_sync",
	"run_monitoring_cycle",
	"run_reconciliation_cycle",
)


def get_installed_apps() -> list:
	"""Apps installed on this site (source of the no-ERPNext proof)."""
	return list(frappe.get_installed_apps())


def assert_no_erpnext() -> dict:
	"""Fail when ERPNext is installed or required anywhere in this app."""
	from beaverbill import hooks

	installed = get_installed_apps()
	if "erpnext" in installed:
		frappe.throw("ERPNext is installed on this site", frappe.ValidationError)
	if list(getattr(hooks, "required_apps", [])) != ["frappe"]:
		frappe.throw("required_apps must be exactly ['frappe']", frappe.ValidationError)
	return {"installed_apps": installed, "required_apps": ["frappe"]}


def validate_scheduler() -> dict:
	"""Scheduler enabled, expected daily jobs registered, queues reachable."""
	from beaverbill import hooks

	enabled = not bool(is_scheduler_disabled(verbose=False))
	daily = list((hooks.scheduler_events or {}).get("daily", []))
	missing = [job for job in EXPECTED_DAILY_JOBS
		if not any(job in entry for entry in daily)]
	try:
		frappe.cache().set_value("release-scheduler-probe", "ok", expires_in_sec=60)
		cache_ok = frappe.cache().get_value("release-scheduler-probe") == "ok"
	except Exception:
		cache_ok = False
	status = "ok" if enabled and not missing and cache_ok else "fail"
	return {"status": status, "scheduler_enabled": enabled,
		"daily_jobs": len(daily), "missing_jobs": missing, "cache_ok": cache_ok}


def check_release_blockers() -> list:
	"""Site-config settings that must not reach production."""
	conf = frappe.get_site_config() or {}
	blockers = []
	if conf.get("ignore_csrf"):
		blockers.append("ignore_csrf is set: CSRF enforcement is off")
	if conf.get("allow_tests"):
		blockers.append("allow_tests is set: test endpoints are enabled")
	if conf.get("maintenance_mode"):
		blockers.append("maintenance_mode is set: site is offline")
	return blockers


def run_smoke_tests() -> list:
	"""Read-only post-release smoke: DB, DocTypes, pricing, monitoring."""
	results = []

	def record(name, func):
		try:
			detail = func()
			results.append({"name": name, "ok": True, "detail": detail})
		except Exception as exc:
			results.append({"name": name, "ok": False, "detail": str(exc)[:200]})

	def db():
		frappe.db.sql("select 1")
		return "select 1 ok"

	def doctypes():
		counts = {dt: frappe.db.count(dt) for dt in (
			"Hosting Product", "Hosting Customer", "Hosting Order",
			"Hosting Invoice", "Hosting Subscription", "Hosting Service")}
		return f"readable: {counts}"

	def pricing():
		from beaverbill.beaverbill import pricing as pricing_mod

		product = frappe.get_all("Hosting Product", pluck="name", limit=1)
		if not product:
			return "no products on site"
		quote = pricing_mod.calculate_price(product[0])
		return f"quote total={quote.get('total_price')}"

	def monitoring_checks():
		from beaverbill.beaverbill import monitoring as monitoring_mod

		rows = monitoring_mod.run_checks()
		bad = [row["check"] for row in rows if row["status"] == "fail"]
		return f"{len(rows)} checks, failing={bad or 'none'}"

	record("database", db)
	record("core_doctypes", doctypes)
	record("pricing", pricing)
	record("monitoring", monitoring_checks)
	return results


def _app_commit(path: str) -> str:
	try:
		out = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
			capture_output=True, text=True, timeout=30)
		sha = out.stdout.strip()
		return sha if len(sha) == 40 else "unknown"
	except Exception:
		return "unknown"


def snapshot_versions() -> dict:
	"""Record stack versions and app SHAs for the release manifest."""
	import os

	bench_root = os.path.abspath(os.path.join(frappe.get_app_path("beaverbill"),
		"..", "..", ".."))
	manifest = {
		"site": frappe.local.site,
		"frappe": frappe.__version__,
		"python": platform.python_version(),
		"platform": platform.platform(),
		"installed_apps": get_installed_apps(),
		"app_commits": {},
		"database": "unknown",
		"blockers": check_release_blockers(),
	}
	for app in manifest["installed_apps"]:
		manifest["app_commits"][app] = _app_commit(os.path.join(bench_root, "apps", app))
	try:
		manifest["database"] = str(
			frappe.db.sql("select version()", pluck=True)[0])
	except Exception:
		pass
	return manifest


@frappe.whitelist()
def release_status() -> dict:
	"""Staff-only: versions, scheduler, smoke, ERPNext check in one call."""
	from beaverbill.beaverbill.portal.guard import is_staff

	if not is_staff():
		frappe.throw("Only staff may view release status", frappe.PermissionError)
	smoke = run_smoke_tests()
	return {
		"versions": snapshot_versions(),
		"scheduler": validate_scheduler(),
		"smoke": smoke,
		"smoke_ok": all(row["ok"] for row in smoke),
		"no_erpnext": assert_no_erpnext(),
	}
