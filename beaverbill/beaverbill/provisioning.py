"""Phase 8 provisioning orchestration: queue, retry, compensate, reconcile.

Wraps the existing drivers in `provisioning_drivers` without changing
their signatures. Legacy direct driver calls keep working; new flows
route through `queue_operation` / `run_operation` for idempotency,
timeouts, classified retries, and audit records.
"""

import json

import frappe
from frappe.utils import add_to_date, now_datetime

from beaverbill.beaverbill import settings as bb_settings
from beaverbill.beaverbill.provisioning_drivers import (
	ProvisioningError,
	call_driver_action,
	classify_exception,
	get_provisioning_driver,
	new_correlation_id,
	request_hash,
	safe_summary,
)

OPERATION_TO_ACTION = {
	"Create": "provision",
	"Suspend": "suspend",
	"Unsuspend": "unsuspend",
	"Terminate": "terminate",
	"Resize": "resize",
	"Reboot": "reboot",
	"Console": "get_vnc_console",
}

# Destructive actions are never blind-retried when the outcome is
# unknown (timeout, lost response); they go to Manual Review instead.
DESTRUCTIVE_ACTIONS = {"terminate"}

TERMINAL_STATUSES = ("Succeeded", "Failed", "Compensated", "Cancelled")
DUE_STATUSES = ("Pending", "Queued", "Retrying")

BACKOFF_BASE_MINUTES = {
	"transient": 5,
	"rate_limited": 15,
	"capacity": 60,
	"permanent": 0,
	"unknown": 30,
}


def _backoff_base() -> dict:
	return {
		"transient": bb_settings.get_int("backoff_transient_minutes", BACKOFF_BASE_MINUTES["transient"]),
		"rate_limited": bb_settings.get_int("backoff_rate_limited_minutes", BACKOFF_BASE_MINUTES["rate_limited"]),
		"capacity": bb_settings.get_int("backoff_capacity_minutes", BACKOFF_BASE_MINUTES["capacity"]),
		"permanent": 0,
		"unknown": bb_settings.get_int("backoff_unknown_minutes", BACKOFF_BASE_MINUTES["unknown"]),
	}


def _backoff_cap() -> int:
	return bb_settings.get_int("backoff_backoff_cap_minutes", 24 * 60)


def _default_timeout() -> int:
	return bb_settings.get_int("timeout_seconds", 300)


def _default_max_retries() -> int:
	return bb_settings.get_int("provisioning_max_retries", 3)

SUCCESS_SERVICE_STATUS = {
	"Create": "Active",
	"Suspend": "Suspended",
	"Unsuspend": "Active",
	"Terminate": "Terminated",
}


def require_staff() -> None:
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles & {"System Manager", "Hosting Admin"}:
		frappe.throw("Only provisioning staff may run this action", frappe.PermissionError)


def backoff_for(error_type: str, retry_count: int) -> int:
	"""Backoff minutes by error type with exponential growth, capped."""
	base = _backoff_base().get(error_type or "unknown", 30)
	if base <= 0:
		return 0
	return min(base * (2 ** max(int(retry_count or 0), 0)), _backoff_cap())


def should_retry(operation_type: str, error_type: str, retryable: bool, retry_count: int, max_retries: int) -> bool:
	"""Decide whether a failed attempt may be retried automatically."""
	action = OPERATION_TO_ACTION.get(operation_type, "")
	if action in DESTRUCTIVE_ACTIONS and error_type == "unknown":
		return False
	if error_type == "permanent":
		return False
	if not retryable:
		return False
	return int(retry_count or 0) < int(max_retries if max_retries is not None else 3)


def queue_operation(
	service: str | None = None,
	subscription: str | None = None,
	operation_type: str = "Create",
	idempotency_key: str | None = None,
	provider_account: str | None = None,
	new_product: str | None = None,
	timeout_seconds: int | None = None,
	max_retries: int | None = None,
	customer: str | None = None,
) -> object:
	"""Queue a provisioning operation; idempotent by `idempotency_key`."""
	timeout_seconds = timeout_seconds or _default_timeout()
	max_retries = _default_max_retries() if max_retries is None else max_retries
	if operation_type not in OPERATION_TO_ACTION:
		frappe.throw(f"Unknown operation type: {operation_type}", frappe.ValidationError)
	if not idempotency_key:
		frappe.throw("Idempotency Key is required", frappe.ValidationError)
	existing = frappe.db.get_value("Provisioning Operation", {"idempotency_key": idempotency_key}, "name")
	if existing:
		return frappe.get_doc("Provisioning Operation", existing)
	if service:
		svc = frappe.get_doc("Hosting Service", service)
		subscription = subscription or svc.subscription
		customer = customer or svc.customer
		provider_account = provider_account or svc.provider_account
	doc = frappe.get_doc(
		{
			"doctype": "Provisioning Operation",
			"service": service,
			"subscription": subscription,
			"customer": customer,
			"operation_type": operation_type,
			"status": "Queued",
			"idempotency_key": idempotency_key,
			"correlation_id": new_correlation_id(),
			"provider_account": provider_account,
			"new_product": new_product,
			"timeout_seconds": timeout_seconds or _default_timeout(),
			"max_retries": max_retries if max_retries is not None else _default_max_retries(),
			"retry_count": 0,
		}
	)
	doc.insert()
	return doc


def _resolve_driver(op: object) -> tuple:
	"""Return (driver_or_None, driver_type). None means simulated legacy path."""
	driver_type = op.driver_type
	account = op.provider_account
	if account and not driver_type:
		driver_type = frappe.db.get_value("Hosting Provider Account", account, "provider_type")
	if not driver_type or driver_type == "Custom":
		return None, driver_type or "Custom"
	try:
		return get_provisioning_driver(driver_type, account), driver_type
	except ValueError as exc:
		raise ProvisioningError(str(exc), error_type="permanent", retryable=False) from exc


def _capacity_check(op: object) -> str | None:
	"""Return a blocking reason when the target node cannot accept work."""
	if not op.service:
		return None
	node = frappe.db.get_value("Hosting Service", op.service, "server_node")
	if not node:
		return None
	status, maintenance = frappe.db.get_value("Server Node", node, ["status", "maintenance_mode"])
	if maintenance:
		return f"Server Node {node} is in maintenance"
	if status in ("Offline", "Decommissioned"):
		return f"Server Node {node} is {status}"
	return None


def _record_attempt(op: object, status: str, error_type: str | None = None, error: str = "",
					request_summary: str = "", response_summary: str = "", duration_ms: int = 0) -> object:
	attempt_no = int(op.attempt_count or 0) + 1
	attempt = frappe.get_doc(
		{
			"doctype": "Provisioning Attempt",
			"operation": op.name,
			"attempt_no": attempt_no,
			"status": status,
			"started_at": op.started_at or now_datetime(),
			"finished_at": now_datetime(),
			"duration_ms": duration_ms,
			"request_summary": (request_summary or "")[:1000],
			"response_summary": (response_summary or "")[:1000],
			"error_type": error_type,
			"error": (error or "")[:1000],
		}
	)
	attempt.insert(ignore_permissions=True)
	op.attempt_count = attempt_no
	return attempt


def _log_request(op: object, action: str, driver_type: str | None, request_summary: str, response_summary: str = "", response_code: str = "", error_type: str | None = None, latency_ms: int = 0) -> None:
	frappe.get_doc(
		{
			"doctype": "Provider Request Log",
			"provider_account": op.provider_account,
			"driver_type": driver_type,
			"operation": op.name,
			"correlation_id": op.correlation_id,
			"action": action,
			"request_hash": request_hash(action, (request_summary,), {}),
			"request_summary": (request_summary or "")[:1000],
			"response_summary": (response_summary or "")[:1000],
			"response_code": response_code or "",
			"error_type": error_type,
			"latency_ms": latency_ms,
			"logged_at": now_datetime(),
		}
	).insert(ignore_permissions=True)


def _sync_service(op: object, result: dict) -> None:
	"""Apply the success outcome to the linked Hosting Service, best effort."""
	if not op.service:
		return
	target = SUCCESS_SERVICE_STATUS.get(op.operation_type)
	if not target:
		return
	try:
		svc = frappe.get_doc("Hosting Service", op.service)
	except frappe.DoesNotExistError:
		return
	if svc.status == target:
		_stamp_reconciled(svc)
		return
	# Walk through Provisioning first so the state machine stays valid.
	if target == "Active" and svc.status == "Pending":
		try:
			svc.status = "Provisioning"
			svc.save(ignore_permissions=True)
		except frappe.ValidationError:
			pass
	try:
		svc.status = target
		meta = {}
		try:
			meta = json.loads(svc.upstream_metadata or "{}")
		except ValueError:
			meta = {}
		meta.update(
			{
				"last_operation": op.name,
				"correlation_id": op.correlation_id,
				"driver_result": {k: v for k, v in (result or {}).items() if k != "password"},
			}
		)
		svc.upstream_metadata = json.dumps(meta, default=str)
		if target == "Active" and op.operation_type == "Create" and result and result.get("ip"):
			try:
				svc.ip_address = result["ip"]
			except Exception:
				pass
		svc.save(ignore_permissions=True)
	except frappe.ValidationError:
		pass
	_stamp_reconciled(svc)


def _stamp_reconciled(svc: object) -> None:
	try:
		frappe.db.set_value(
			"Hosting Service",
			svc.name,
			{"last_reconciled_at": now_datetime(), "reconciliation_status": "Matched"},
		)
	except Exception:
		pass


def _fail_operation(op: object, error_type: str, message: str, retryable: bool) -> object:
	op.error_type = error_type
	op.last_error = (message or "")[:1000]
	if should_retry(op.operation_type, error_type, retryable, op.retry_count, op.max_retries):
		op.retry_count = int(op.retry_count or 0) + 1
		op.status = "Retrying"
		op.next_retry_at = add_to_date(now_datetime(), minutes=backoff_for(error_type, op.retry_count))
	else:
		op.status = "Manual Review" if error_type == "unknown" or (
			OPERATION_TO_ACTION.get(op.operation_type) in DESTRUCTIVE_ACTIONS
		) else "Failed"
		if op.status == "Failed":
			_create_cleanup_tasks(op, f"Operation failed ({error_type}): {(message or '')[:200]}")
	op.finished_at = now_datetime()
	op.save(ignore_permissions=True)
	return op


def _create_cleanup_tasks(op: object, detail: str) -> list:
	"""Partial-failure compensation: leave explicit cleanup work items."""
	task_types = ["Manual Check"]
	if op.operation_type == "Create":
		task_types = ["Release IP", "Manual Check"]
	elif op.operation_type == "Terminate":
		task_types = ["Remove DNS", "Revoke Console", "Manual Check"]
	elif op.operation_type == "Resize":
		task_types = ["Restore Snapshot", "Manual Check"]
	created = []
	for task_type in task_types:
		task = frappe.get_doc(
			{
				"doctype": "Resource Cleanup Task",
				"service": op.service,
				"operation": op.name,
				"task_type": task_type,
				"status": "Pending",
				"details": detail,
			}
		)
		task.insert(ignore_permissions=True)
		created.append(task.name)
	return created


def run_operation(name: str) -> object:
	"""Execute one queued/due operation synchronously with full auditing."""
	op = frappe.get_doc("Provisioning Operation", name)
	if op.status in TERMINAL_STATUSES:
		return op
	if op.status == "Retrying" and op.next_retry_at and get_now() < op.next_retry_at:
		return op
	# Lock the row so overlapping scheduler runs cannot double-execute.
	frappe.db.get_value("Provisioning Operation", name, "name", for_update=True)
	op.reload()
	if op.status in TERMINAL_STATUSES:
		return op
	action = OPERATION_TO_ACTION.get(op.operation_type)
	if not action:
		return _fail_operation(op, "permanent", f"Unknown operation type: {op.operation_type}", False)

	# Stale Running runs are treated as unknown outcomes (possible timeout).
	if op.status == "Running" and op.started_at:
		elapsed = (now_datetime() - op.started_at).total_seconds()
		if elapsed < int(op.timeout_seconds or _default_timeout()):
			return op
		_record_attempt(op, "Failed", "unknown", "Previous run timed out; outcome unknown")
		_log_request(op, action, op.driver_type, "stale-run-timeout", error_type="unknown")
		return _fail_operation(op, "unknown", "Previous run timed out; outcome unknown", False)

	blocked = _capacity_check(op)
	if blocked:
		_record_attempt(op, "Failed", "capacity", blocked, request_summary="capacity-check")
		_log_request(op, action, op.driver_type, "capacity-check", response_summary=blocked, response_code="blocked", error_type="capacity")
		return _fail_operation(op, "capacity", blocked, True)

	op.status = "Running"
	op.started_at = now_datetime()
	if not op.correlation_id:
		op.correlation_id = new_correlation_id()
	op.save(ignore_permissions=True)

	try:
		driver, driver_type = _resolve_driver(op)
		op.driver_type = driver_type
	except ProvisioningError as exc:
		_record_attempt(op, "Failed", exc.error_type, str(exc), request_summary="driver-resolve")
		_log_request(op, action, op.driver_type, "driver-resolve", response_code="unresolved", error_type=exc.error_type)
		return _fail_operation(op, exc.error_type, str(exc), exc.retryable)

	subject = op.subscription or op.service or op.name
	request_summary = f"{action} subject={subject} correlation={op.correlation_id}"
	try:
		if driver is None:
			# Preserved simulated path for Custom/missing providers.
			frappe.logger().info(f"Simulated {action} for {subject} ({op.correlation_id})")
			result, elapsed_ms = {"status": "Success", "simulated": True}, 0
		else:
			args = _driver_args(op, action, subject)
			result, elapsed_ms = call_driver_action(driver, action, *args[0], **args[1])
	except ProvisioningError as exc:
		_record_attempt(op, "Failed", exc.error_type, str(exc), request_summary=request_summary)
		_log_request(op, action, driver_type, request_summary, response_code="error", error_type=exc.error_type, latency_ms=0)
		return _fail_operation(op, exc.error_type, str(exc), exc.retryable)

	_record_attempt(op, "Succeeded", request_summary=request_summary,
					response_summary=safe_summary(result), duration_ms=elapsed_ms)
	_log_request(op, action, driver_type, request_summary, response_summary=safe_summary(result), response_code="ok", latency_ms=elapsed_ms)
	try:
		op.provider_metadata = json.dumps(
			{"result": result, "correlation_id": op.correlation_id, "driver_type": driver_type},
			default=str,
		)[:4000]
	except ValueError:
		op.provider_metadata = "{}"
	op.status = "Succeeded"
	op.finished_at = now_datetime()
	op.error_type = None
	op.last_error = None
	op.save(ignore_permissions=True)
	_sync_service(op, result)
	return op


def _driver_args(op: object, action: str, subject: str) -> tuple:
	"""Build (args, kwargs) for a driver verb from the operation row."""
	if action == "provision":
		return ((subject, {"operation": op.name, "correlation_id": op.correlation_id}), {})
	if action == "resize":
		return ((subject, op.new_product or ""), {})
	return ((subject,), {})


def get_now() -> object:
	return now_datetime()


def process_queued_operations(limit: int | None = None) -> dict:
	"""Scheduler worker: run due operations. Idempotent and lock-safe."""
	limit = limit or bb_settings.get_int("queue_batch_limit", 50)
	due = frappe.get_all(
		"Provisioning Operation",
		filters={"status": ("in", list(DUE_STATUSES))},
		fields=["name", "status", "next_retry_at"],
		order_by="creation asc",
		limit_page_length=limit,
	)
	ran = {"succeeded": 0, "failed": 0, "retries": 0, "manual_review": 0, "skipped": 0}
	for row in due:
		try:
			op = run_operation(row.name)
			if op.status == "Succeeded":
				ran["succeeded"] += 1
			elif op.status == "Retrying":
				ran["retries"] += 1
			elif op.status == "Manual Review":
				ran["manual_review"] += 1
			elif op.status in ("Failed", "Compensated", "Cancelled"):
				ran["failed"] += 1
			else:
				ran["skipped"] += 1
		except Exception as exc:
			frappe.logger().error(f"Provisioning worker error on {row.name}: {exc}")
			ran["skipped"] += 1
		frappe.db.commit()
	return ran


@frappe.whitelist()
def retry_operation(name: str) -> dict:
	"""Staff action: requeue a Failed / Manual Review operation."""
	require_staff()
	op = frappe.get_doc("Provisioning Operation", name)
	if op.status not in ("Failed", "Manual Review", "Retrying"):
		frappe.throw(f"Only Failed or Manual Review operations can be retried, not {op.status}", frappe.ValidationError)
	op.status = "Queued"
	op.next_retry_at = None
	op.last_error = None
	op.error_type = None
	op.save()
	return {"operation": op.name, "status": op.status}


@frappe.whitelist()
def cancel_operation(name: str) -> dict:
	"""Staff action: cancel an operation that has not succeeded."""
	require_staff()
	op = frappe.get_doc("Provisioning Operation", name)
	if op.status in TERMINAL_STATUSES:
		frappe.throw(f"Terminal operation {op.status} cannot be cancelled", frappe.ValidationError)
	op.status = "Cancelled"
	op.finished_at = now_datetime()
	op.save()
	return {"operation": op.name, "status": op.status}


@frappe.whitelist()
def compensate_operation(name: str, note: str = "") -> dict:
	"""Staff action: mark partial-failure compensation complete."""
	require_staff()
	op = frappe.get_doc("Provisioning Operation", name)
	if op.status not in ("Failed", "Manual Review", "Succeeded"):
		frappe.throw(f"Operation {op.status} needs no compensation", frappe.ValidationError)
	tasks = _create_cleanup_tasks(op, (note or "Manual compensation")[:500])
	op.status = "Compensated"
	op.finished_at = now_datetime()
	op.save(ignore_permissions=True)
	return {"operation": op.name, "status": op.status, "cleanup_tasks": tasks}


STATE_ALIASES = {
	"active": "Active",
	"running": "Active",
	"on": "Active",
	"provisioning": "Provisioning",
	"creating": "Provisioning",
	"suspended": "Suspended",
	"suspend": "Suspended",
	"off": "Suspended",
	"terminated": "Terminated",
	"deleted": "Terminated",
	"destroyed": "Terminated",
	"absent": "Terminated",
	"missing": "Terminated",
}


def _normalize_remote(remote: object) -> str | None:
	if remote is None:
		return None
	if isinstance(remote, dict):
		for key in ("status", "state", "power_state", "exists"):
			if key in remote:
				value = remote[key]
				if isinstance(value, bool):
					return "Active" if value else "Terminated"
				return STATE_ALIASES.get(str(value).strip().lower(), str(value))
		return None
	return STATE_ALIASES.get(str(remote).strip().lower(), str(remote))


def reconcile_service(service_name: str, remote_state: object = None, operation: str | None = None) -> object:
	"""Compare local service state against the provider and record verdict.

	`remote_state` may be injected (tests, staff discovery); otherwise the
	driver's `describe` is used. Drivers without `describe` yield Unknown.
	"""
	svc = frappe.get_doc("Hosting Service", service_name)
	local_state = svc.status
	remote = remote_state
	driver_type = None
	if remote is None:
		account = svc.provider_account
		if account:
			driver_type = frappe.db.get_value("Hosting Provider Account", account, "provider_type")
		if driver_type and driver_type != "Custom":
			try:
				driver = get_provisioning_driver(driver_type, account)
				try:
					remote, _elapsed = call_driver_action(
						driver, "describe", svc.subscription or service_name)
				except ProvisioningError as exc:
					return _store_verdict(svc, None, "Unknown", f"describe failed ({exc.error_type}): {exc}", operation)
			except (ValueError, ProvisioningError) as exc:
				return _store_verdict(svc, None, "Unknown", f"driver unavailable: {exc}", operation)
		else:
			return _store_verdict(svc, None, "Unknown", "No provider driver; simulated path", operation)
	remote_norm = _normalize_remote(remote)
	if remote_norm is None:
		verdict, details = "Unknown", f"Unrecognized remote state: {safe_summary(remote, 300)}"
	elif local_state == "Terminated" and remote_norm != "Terminated":
		verdict, details = "Orphaned Remote", f"Local Terminated but provider reports {remote_norm}"
	elif local_state != "Terminated" and remote_norm == "Terminated":
		verdict, details = "Orphaned Local", "Provider reports resource missing"
	elif local_state == remote_norm or (local_state == "Active" and remote_norm == "Active"):
		verdict, details = "Matched", f"Local and remote agree on {local_state}"
	else:
		verdict, details = "Mismatched", f"Local {local_state} vs remote {remote_norm}"
	return _store_verdict(svc, remote_norm, verdict, details, operation)


def _store_verdict(svc: object, remote_norm: str | None, verdict: str, details: str, operation: str | None = None) -> object:
	result = frappe.get_doc(
		{
			"doctype": "Reconciliation Result",
			"service": svc.name,
			"provider_account": svc.provider_account,
			"operation": operation,
			"local_state": svc.status,
			"remote_state": remote_norm,
			"verdict": verdict,
			"details": details[:1000],
			"checked_at": now_datetime(),
		}
	)
	result.insert(ignore_permissions=True)
	updates = {"last_reconciled_at": now_datetime(), "reconciliation_notes": details[:1000]}
	if verdict in ("Matched", "Mismatched"):
		updates["reconciliation_status"] = verdict
	elif verdict != "Unknown":
		updates["reconciliation_notes"] = f"{verdict}: {details}"[:1000]
	try:
		# set_value avoids clobbering concurrent service edits.
		frappe.db.set_value("Hosting Service", svc.name, updates)
	except Exception:
		pass
	return result


@frappe.whitelist()
def reconcile_now(service_name: str) -> dict:
	"""Staff action: reconcile one service immediately."""
	require_staff()
	result = reconcile_service(service_name)
	return {"service": service_name, "verdict": result.verdict, "details": result.details}


def orphaned_resources(provider_account: str | None = None) -> list:
	"""List services whose latest verdict signals an orphan on either side."""
	filters = {"verdict": ("in", ["Orphaned Local", "Orphaned Remote", "Mismatched"])}
	if provider_account:
		filters["provider_account"] = provider_account
	names = frappe.get_all("Reconciliation Result", filters=filters, fields=["service", "verdict", "details", "checked_at"], order_by="checked_at desc")
	seen = {}
	for row in names:
		seen.setdefault(row.service, row)
	return list(seen.values())


def classify_error_for_tests(exc: Exception) -> tuple:
	"""Pure helper exposed for contract tests (no DB access)."""
	return classify_exception(exc)
