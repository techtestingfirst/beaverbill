"""Central BeaverBill settings: one Single DocType for every tunable.

All engines read through `beaverbill.beaverbill.settings.get_value` with a
hard default fallback, so a missing/unmigrated site keeps legacy behavior.
Staff edit values in Desk at BeaverBill Settings; no code change needed.
"""

from __future__ import annotations

import frappe

DOCTYPE = "BeaverBill Settings"

# Fieldname -> legacy hardcoded default. Single source of truth for fallbacks.
DEFAULTS: dict = {
	# Billing
	"default_currency": "USD",
	# Subscriptions
	"terminate_after_suspend_days": 14,
	"purge_after_terminate_days": 30,
	"sub_default_max_retries": 4,
	"sub_default_grace_period_days": 7,
	"sub_default_renewal_lead_days": 3,
	"sub_default_retry_backoff_minutes": 240,
	"lock_timeout_minutes": 10,
	# Domains
	"domain_renewal_price": 15.0,
	"domain_renewal_currency": "USD",
	"domain_reminder_stages": "30,14,7,1",
	"auto_renew_within_days": 7,
	"domain_grace_days": 30,
	"domain_redemption_days": 30,
	"default_dns_ttl": 3600,
	# Provisioning
	"timeout_seconds": 300,
	"queue_batch_limit": 50,
	"backoff_transient_minutes": 5,
	"backoff_rate_limited_minutes": 15,
	"backoff_capacity_minutes": 60,
	"backoff_unknown_minutes": 30,
	"backoff_backoff_cap_minutes": 1440,
	# Certificates
	"cert_validity_days": 90,
	"cert_expiry_warn_days": 30,
	"cert_stale_validation_days": 7,
	# Backups
	"backup_expired_purge_days": 7,
	"backup_default_retention_days": 30,
	"backup_default_snapshot_size_mb": 512.0,
	# Security / identity
	"max_upload_mb": 5,
	"max_provider_response_kb": 256,
	"session_ttl_hours": 12,
	"console_ttl_minutes": 15,
	"verification_ttl_hours": 24,
	"token_default_ttl_hours": 12,
	"login_fail_limit": 5,
	"login_fail_window_minutes": 15,
	"login_lock_minutes": 15,
	"min_password_length": 8,
	# Portal
	"portal_default_rate_limit": 120,
	"portal_default_rate_window_sec": 60,
	"cart_ttl_days": 7,
	# Helpdesk sync
	"sync_max_attempts": 5,
	"sync_backoff_base_minutes": 5,
	"sync_backoff_cap_minutes": 240,
	# Monitoring / reconciliation
	"expiring_warn_days": 30,
	"expiring_urgent_days": 7,
	"invoice_overdue_flag_days": 90,
	"recon_batch_limit": 50,
	"ip_low_threshold_pct": 10,
}


def get_value(key: str, default=None):
	"""Return one setting value, falling back to DEFAULTS then `default`."""
	fallback = DEFAULTS.get(key, default)
	try:
		value = frappe.db.get_single_value(DOCTYPE, key)
	except Exception:
		return fallback
	if value is None or value == "":
		return fallback
	# Fresh Single rows store Int/Float as 0 until staff saves; 0 is never
	# a meaningful value for any BeaverBill tunable, so fall back then too.
	if value == 0 or value == 0.0:
		return fallback
	return value


def get_int(key: str, default: int = 0) -> int:
	try:
		return int(float(get_value(key, default)))
	except (TypeError, ValueError):
		return int(default)


def get_float(key: str, default: float = 0.0) -> float:
	try:
		return float(get_value(key, default))  # type: ignore[arg-type]
	except (TypeError, ValueError):
		return float(default)


def get_str(key: str, default: str = "") -> str:
	value = get_value(key, default)
	return str(value) if value is not None else str(default)


def get_all() -> dict:
	"""Return every setting with defaults applied."""
	return {key: get_value(key, dv) for key, dv in DEFAULTS.items()}


def get_reminder_stages() -> tuple:
	"""Parse `domain_reminder_stages` ("30,14,7,1") into a tuple of ints."""
	raw = get_str("domain_reminder_stages", "30,14,7,1")
	stages = []
	for part in str(raw).split(","):
		part = part.strip()
		if part:
			try:
				stages.append(int(float(part)))
			except ValueError:
				continue
	return tuple(stages) or (30, 14, 7, 1)


@frappe.whitelist()
def get_public_settings() -> dict:
	"""Safe subset for the portal (no secrets; all values already non-secret)."""
	from beaverbill.beaverbill.portal.guard import is_staff

	if not is_staff():
		frappe.throw("Only staff may view settings", frappe.PermissionError)
	return get_all()
