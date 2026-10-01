import frappe
from frappe.model.document import Document


class BeaverBillSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		auto_renew_within_days: DF.Int | None
		backoff_backoff_cap_minutes: DF.Int | None
		backoff_capacity_minutes: DF.Int | None
		backoff_rate_limited_minutes: DF.Int | None
		backoff_transient_minutes: DF.Int | None
		backoff_unknown_minutes: DF.Int | None
		backup_default_retention_days: DF.Int | None
		backup_default_snapshot_size_mb: DF.Float | None
		backup_expired_purge_days: DF.Int | None
		billing_col: DF.ColumnBreak | None
		billing_section: DF.SectionBreak | None
		billing_tab: DF.TabBreak | None
		cart_ttl_days: DF.Int | None
		cert_expiry_warn_days: DF.Int | None
		cert_stale_validation_days: DF.Int | None
		cert_validity_days: DF.Int | None
		certs_col: DF.ColumnBreak | None
		certs_tab: DF.TabBreak | None
		certs_section: DF.SectionBreak | None
		console_ttl_minutes: DF.Int | None
		default_currency: DF.Data | None
		default_dns_ttl: DF.Int | None
		domain_grace_days: DF.Int | None
		domain_redemption_days: DF.Int | None
		domain_reminder_stages: DF.Data | None
		domain_renewal_currency: DF.Data | None
		domain_renewal_price: DF.Currency | None
		domains_col: DF.ColumnBreak | None
		domains_tab: DF.TabBreak | None
		domains_section: DF.SectionBreak | None
		expiring_urgent_days: DF.Int | None
		expiring_warn_days: DF.Int | None
		helpdesk_col: DF.ColumnBreak | None
		helpdesk_section: DF.SectionBreak | None
		helpdesk_tab: DF.TabBreak | None
		invoice_overdue_flag_days: DF.Int | None
		ip_low_threshold_pct: DF.Percent | None
		lock_timeout_minutes: DF.Int | None
		login_fail_limit: DF.Int | None
		login_fail_window_minutes: DF.Int | None
		login_lock_minutes: DF.Int | None
		max_provider_response_kb: DF.Int | None
		max_upload_mb: DF.Int | None
		min_password_length: DF.Int | None
		monitoring_col: DF.ColumnBreak | None
		monitoring_section: DF.SectionBreak | None
		monitoring_tab: DF.TabBreak | None
		portal_default_rate_limit: DF.Int | None
		portal_default_rate_window_sec: DF.Int | None
		portal_col: DF.ColumnBreak | None
		portal_section: DF.SectionBreak | None
		portal_tab: DF.TabBreak | None
		provisioning_col: DF.ColumnBreak | None
		provisioning_section: DF.SectionBreak | None
		provisioning_tab: DF.TabBreak | None
		purge_after_terminate_days: DF.Int | None
		queue_batch_limit: DF.Int | None
		recon_batch_limit: DF.Int | None
		security_col: DF.ColumnBreak | None
		security_section: DF.SectionBreak | None
		security_tab: DF.TabBreak | None
		session_ttl_hours: DF.Int | None
		sub_default_grace_period_days: DF.Int | None
		sub_default_max_retries: DF.Int | None
		sub_default_renewal_lead_days: DF.Int | None
		sub_default_retry_backoff_minutes: DF.Int | None
		subscriptions_col: DF.ColumnBreak | None
		subscriptions_section: DF.SectionBreak | None
		subscriptions_tab: DF.TabBreak | None
		sync_backoff_base_minutes: DF.Int | None
		sync_backoff_cap_minutes: DF.Int | None
		sync_max_attempts: DF.Int | None
		terminate_after_suspend_days: DF.Int | None
		timeout_seconds: DF.Int | None
		token_default_ttl_hours: DF.Int | None
		verification_ttl_hours: DF.Int | None
	# end: auto-generated types

	pass
