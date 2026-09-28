"""Phase 9 backup engine: policies, execution, retention, restores, overage."""

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime, today

from beaverbill.beaverbill import billing
from beaverbill.beaverbill.notifications import billable_customer, notify, require_staff

FREQUENCY_INTERVALS = {
	"Manual": None,
	"Daily": {"days": 1},
	"Weekly": {"days": 7},
	"Monthly": {"days": 30},
}

EXPIRED_PURGE_DAYS = 7

# Fault injection for tests: {"run": msg, "restore": msg}
BACKUP_FAULTS: dict = {}


def _next_run(frequency: str, base=None):
	delta = FREQUENCY_INTERVALS.get(frequency or "Manual")
	if not delta:
		return None
	return add_to_date(base or now_datetime(), **delta)


@frappe.whitelist()
def run_backup(policy_name: str) -> dict:
	"""Execute one backup for a policy (simulated storage write)."""
	policy = frappe.get_doc("Backup Policy", policy_name)
	backup = frappe.get_doc(
		{
			"doctype": "Service Backup",
			"policy": policy.name,
			"service": policy.service,
			"customer": policy.customer,
			"status": "In Progress",
			"started_at": now_datetime(),
			"storage_location": policy.storage_location,
			"retain_until": add_days(getdate(today()), int(policy.retention_days or 30)),
		}
	).insert()
	if BACKUP_FAULTS.get("run"):
		backup.status = "Failed"
		backup.failure_reason = BACKUP_FAULTS["run"][:1000]
		backup.finished_at = now_datetime()
		backup.save()
		notify(policy.customer, f"Backup failed for service {policy.service}",
			   f"{BACKUP_FAULTS['run']} The next scheduled run will retry.",
			   "Service Backup", backup.name)
		return {"backup": backup.name, "status": backup.status, "error": BACKUP_FAULTS["run"]}
	# Simulated snapshot size; real drivers report actual bytes in later phases.
	backup.size_mb = 512.0
	backup.status = "Completed"
	backup.finished_at = now_datetime()
	backup.save()
	policy.last_run_at = now_datetime()
	policy.next_run_at = _next_run(policy.frequency)
	policy.save(ignore_permissions=True)
	return {"backup": backup.name, "status": backup.status}


def run_due_backups() -> dict:
	"""Scheduler: run every enabled policy whose next run is due."""
	ran = {"started": 0}
	now = now_datetime()
	for row in frappe.get_all("Backup Policy", filters={"enabled": 1}, fields=["name", "frequency", "next_run_at"]):
		if row.frequency == "Manual":
			continue
		if not row.next_run_at:
			policy = frappe.get_doc("Backup Policy", row.name)
			policy.next_run_at = _next_run(policy.frequency) or now
			policy.save(ignore_permissions=True)
			row.next_run_at = policy.next_run_at
		if getdate(row.next_run_at) <= getdate(today()):
			try:
				run_backup(row.name)
				ran["started"] += 1
			except Exception as exc:
				frappe.logger().error(f"Backup run failed for {row.name}: {exc}")
		frappe.db.commit()
	return ran


def enforce_retention() -> dict:
	"""Expire backups past retain_until, purge old expired ones, trim counts."""
	day = getdate(today())
	ran = {"expired": 0, "deleted": 0}
	for row in frappe.get_all("Service Backup", filters={"status": "Completed"}, fields=["name", "retain_until"]):
		if row.retain_until and getdate(row.retain_until) < day:
			doc = frappe.get_doc("Service Backup", row.name)
			doc.status = "Expired"
			doc.save(ignore_permissions=True)
			ran["expired"] += 1
	cutoff = add_days(day, -EXPIRED_PURGE_DAYS)
	for row in frappe.get_all("Service Backup", filters={"status": "Expired"}, fields=["name", "modified"]):
		if getdate(row.modified) < cutoff:
			doc = frappe.get_doc("Service Backup", row.name)
			doc.status = "Deleted"
			doc.save(ignore_permissions=True)
			ran["deleted"] += 1
	for policy in frappe.get_all("Backup Policy", pluck="name"):
		limit = int(frappe.db.get_value("Backup Policy", policy, "retention_count") or 0)
		kept = frappe.get_all(
			"Service Backup",
			filters={"policy": policy, "status": "Completed"},
			pluck="name",
			order_by="creation desc",
		)
		for extra in kept[limit:]:
			doc = frappe.get_doc("Service Backup", extra)
			doc.status = "Expired"
			doc.save(ignore_permissions=True)
			ran["expired"] += 1
		frappe.db.commit()
	return ran


@frappe.whitelist()
def request_restore(backup_name: str, service: str) -> dict:
	"""Request a restore. Anyone with create permission may ask; staff approve."""
	backup = frappe.get_doc("Service Backup", backup_name)
	if backup.status != "Completed":
		frappe.throw(f"Only Completed backups can be restored, not {backup.status}", frappe.ValidationError)
	if backup.service != service:
		frappe.throw("Restore target must match the backup's service", frappe.ValidationError)
	req = frappe.get_doc(
		{
			"doctype": "Restore Request",
			"backup": backup.name,
			"service": service,
			"customer": backup.customer,
			"status": "Pending",
		}
	).insert()
	notify(backup.customer, "Restore requested", f"Restore of {service} is pending staff approval.",
		   "Restore Request", req.name)
	return {"restore": req.name, "status": req.status}


@frappe.whitelist()
def approve_restore(name: str, note: str = "") -> dict:
	"""Staff authorization gate: a restore never runs without approval."""
	require_staff()
	req = frappe.get_doc("Restore Request", name)
	if req.status not in ("Pending", "Failed"):
		frappe.throw(f"Restore {req.status} cannot be approved", frappe.ValidationError)
	req.status = "Approved"
	req.approved_by = frappe.session.user
	req.authorization_note = (note or "")[:1000]
	req.save()
	return execute_restore(req.name)


@frappe.whitelist()
def reject_restore(name: str, note: str = "") -> dict:
	require_staff()
	req = frappe.get_doc("Restore Request", name)
	if req.status != "Pending":
		frappe.throw(f"Restore {req.status} cannot be rejected", frappe.ValidationError)
	req.status = "Rejected"
	req.authorization_note = (note or "")[:1000]
	req.completed_at = now_datetime()
	req.save()
	return {"restore": req.name, "status": req.status}


def execute_restore(name: str) -> dict:
	req = frappe.get_doc("Restore Request", name)
	if req.status != "Approved":
		frappe.throw(f"Only Approved restores can execute, not {req.status}", frappe.ValidationError)
	req.status = "In Progress"
	req.save()
	if BACKUP_FAULTS.get("restore"):
		req.status = "Failed"
		req.failure_reason = BACKUP_FAULTS["restore"][:1000]
		req.save()
		notify(req.customer, "Restore failed", f"{BACKUP_FAULTS['restore']} Staff can re-approve to retry.",
			   "Restore Request", req.name)
		return {"restore": req.name, "status": req.status, "error": BACKUP_FAULTS["restore"]}
	req.status = "Completed"
	req.completed_at = now_datetime()
	req.save()
	notify(req.customer, "Restore completed", f"Service {req.service} was restored from backup {req.backup}.",
		   "Restore Request", req.name)
	return {"restore": req.name, "status": req.status}


def record_storage_usage(service: str, used_gb: float, quota_gb: float, overage_rate: float = 0) -> object:
	"""Record a storage measurement; overage is derived in validate."""
	snap = frappe.get_doc(
		{
			"doctype": "Service Storage Usage",
			"service": service,
			"used_gb": used_gb,
			"quota_gb": quota_gb,
			"overage_rate": overage_rate or 0,
		}
	).insert()
	if snap.overage_gb > 0:
		notify(snap.customer, f"Storage overage on {service}",
			   f"Usage {used_gb} GB exceeds quota {quota_gb} GB by {snap.overage_gb} GB.",
			   "Service Storage Usage", snap.name)
		frappe.db.set_value("Service Storage Usage", snap.name, "notified", 1)
	return snap


def process_storage_overage() -> dict:
	"""Invoice uninvoiced overage snapshots once each (idempotent)."""
	ran = {"invoiced": 0, "notified": 0}
	for row in frappe.get_all(
		"Service Storage Usage",
		filters={"overage_invoice": ("in", ["", None])},
		fields=["name", "service", "customer", "overage_gb", "overage_rate"],
	):
		if float(row.overage_gb or 0) <= 0:
			continue
		amount = round(float(row.overage_gb) * float(row.overage_rate or 0), 2)
		if amount <= 0:
			continue
		invoice = billing.issue_invoice(
			billable_customer(row.customer),
			[{
				"description": f"Storage overage {row.service}: {row.overage_gb} GB",
				"qty": 1,
				"unit_price": amount,
				"line_total": amount,
			}],
			currency="USD",
			idempotency_key=f"overage-{row.name}",
		)
		frappe.db.set_value(
			"Service Storage Usage", row.name,
			{"overage_invoice": invoice.name, "notified": 1},
		)
		ran["invoiced"] += 1
		notify(row.customer, f"Storage overage invoiced for {row.service}",
			   f"Invoice {invoice.name} covers {row.overage_gb} GB of overage.",
			   "Service Storage Usage", row.name)
		frappe.db.commit()
	return ran
