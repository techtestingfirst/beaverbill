"""Add Section Break / Column Break layout to all parent DocTypes.

SPEC maps DocType name -> list of (section_label, col_a, col_b).
Every existing field must appear exactly once. Additive only.
"""

import json
import glob
import os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "beaverbill", "beaverbill", "doctype")

SPEC = {
    "Backup Policy": [
        ("Details", ["policy_name", "service", "customer"], ["frequency", "enabled"]),
        ("Schedule", ["retention_count", "retention_days"], ["storage_location"]),
        ("Runs", ["last_run_at"], ["next_run_at"]),
    ],
    "Customer Credit Transaction": [
        ("Transaction", ["customer", "hosting_customer", "transaction_date"], ["amount", "currency", "type"]),
        ("Ledger", ["balance_after"], ["description"]),
        ("References", ["source_type", "source_name"], ["reversal_of", "idempotency_key"]),
    ],
    "Customer Notification": [
        ("Message", ["customer", "user"], ["subject"]),
        ("Content", ["message"], []),
        ("Status", ["read"], ["created_at"]),
    ],
    "Datacenter Asset": [
        ("Asset", ["asset_name", "asset_type"], ["datacenter", "status"]),
        ("Location", ["rack_location"], ["u_position"]),
    ],
    "Domain Registrar Account": [
        ("Registrar", ["registrar_name", "registrar"], ["api_endpoint"]),
        ("Credentials", ["credential_reference"], ["is_active", "auto_renew_default"]),
        ("TLDs", ["supported_tlds"], []),
    ],
    "Helpdesk Sync Log": [
        ("Sync", ["entity_type", "entity"], ["hd_name", "status"]),
        ("Retries", ["attempts", "max_attempts"], ["next_retry_at"]),
        ("Error", ["error_type"], ["last_error"]),
        ("Key", ["idempotency_key"], []),
    ],
    "Hosting Configurable Option": [
        ("Option", ["option_name", "product"], ["option_type", "price_per_unit"]),
    ],
    "Hosting Credit Note": [
        ("Credit", ["customer", "invoice", "credit_date"], ["amount", "currency", "status"]),
        ("Details", ["reason"], ["reversal_of", "idempotency_key"]),
    ],
    "Hosting Currency Exchange Rate": [
        ("Rate", ["from_currency", "to_currency"], ["rate", "effective_date"]),
    ],
    "Hosting Customer": [
        ("Identity", ["customer_name", "customer_type"], ["company_name", "status"]),
        ("Account", ["primary_user", "customer_group"], ["tax_profile"]),
        ("Locale", ["locale"], ["timezone"]),
        ("Verification", ["email_verified", "identity_verified"], ["consent_terms", "consent_marketing", "consent_datetime"]),
        ("Notes", ["notes"], []),
    ],
    "Hosting Customer Contact": [
        ("Contact", ["customer", "contact_type"], ["full_name"]),
        ("Reach", ["email"], ["phone", "is_primary"]),
    ],
    "Hosting Customer Group": [
        ("Group", ["customer_group_name"], ["description"]),
    ],
    "Hosting Customer Tax Profile": [
        ("Profile", ["user", "customer"], ["country", "state"]),
        ("Tax", ["tax_exempt"], ["gstin"]),
    ],
    "Hosting Datacenter": [
        ("Datacenter", ["datacenter_name", "region"], ["availability_zone", "status"]),
        ("Notes", ["notes"], []),
    ],
    "Hosting Debit Note": [
        ("Debit", ["customer", "invoice", "debit_date"], ["amount", "currency", "status"]),
        ("Details", ["reason"], ["reversal_of", "idempotency_key"]),
    ],
    "Hosting DNS Record": [
        ("Record", ["domain", "record_type"], ["host", "value"]),
        ("Settings", ["ttl", "priority"], ["status"]),
    ],
    "Hosting Domain": [
        ("Domain", ["domain_name", "customer"], ["service", "registrar_account"]),
        ("Status", ["status", "transfer_status"], ["auto_renew"]),
        ("Dates", ["registration_date", "expiry_date"], ["last_reminder_at", "last_reminder_stage"]),
        ("Security", ["nameservers"], ["auth_code"]),
        ("Billing", ["idempotency_key", "renewal_idempotency_key"], ["renewal_invoice"]),
        ("Issues", ["failure_reason"], ["cancelled_at"]),
    ],
    "Hosting Invoice": [
        ("Parties", ["customer", "hosting_customer"], ["invoice_date", "due_date", "status"]),
        ("Amounts", ["subtotal", "discount_amount"], ["tax_amount", "total_amount"]),
        ("Payments", ["paid_amount", "outstanding_amount"], ["currency", "order"]),
        ("Items", ["items"], []),
        ("Meta", ["pricing_snapshot"], ["idempotency_key"]),
        ("Source", ["source_type", "source_name"], ["reversal_of"]),
        ("Documents", ["reversal_reason", "cancellation_reason"], ["invoice_pdf"]),
    ],
    "Hosting Order": [
        ("Order", ["customer", "hosting_customer"], ["order_date", "status"]),
        ("Payment", ["promo_code", "currency"], ["total_amount"]),
        ("Items", ["items"], []),
        ("Close", ["idempotency_key"], ["cancellation_reason"]),
    ],
    "Hosting Payment Allocation": [
        ("Allocation", ["payment", "invoice"], ["allocated_amount", "allocation_date"]),
        ("References", ["idempotency_key"], ["reversed_against", "remarks"]),
    ],
    "Hosting Payment Event": [
        ("Event", ["event_id", "gateway"], ["event_type", "payload_hash"]),
        ("Payload", ["payload"], []),
        ("Verification", ["signature_valid"], ["status", "payment"]),
        ("Retry", ["attempts"], ["last_error", "idempotency_key"]),
    ],
    "Hosting Payment Gateway": [
        ("Gateway", ["gateway_name", "provider"], ["supported_currencies"]),
        ("Currency", ["default_currency"], ["is_active"]),
        ("Credentials", ["webhook_secret"], []),
        ("Simulation", ["maintenance_mode"], ["max_retries", "retry_backoff_minutes"]),
    ],
    "Hosting Payment Method": [
        ("Method", ["customer", "gateway"], ["token_reference"]),
        ("Card", ["brand", "last4"], ["exp_month", "exp_year", "is_default"]),
    ],
    "Hosting Payment Transaction": [
        ("Payment", ["customer", "payment_date"], ["amount", "currency", "status"]),
        ("Gateway", ["gateway", "gateway_reference"], ["gateway_event_id", "payment_token_ref"]),
        ("Retry", ["retry_count", "next_retry_at"], ["last_error"]),
        ("References", ["idempotency_key", "source_invoice"], ["remarks"]),
    ],
    "Hosting Product": [
        ("Product", ["product_name", "product_group"], ["billing_cycle"]),
        ("Pricing", ["price"], ["currency"]),
        ("Details", ["description"], []),
        ("Specs", ["cpu_cores", "ram_mb"], ["disk_gb", "bandwidth_gb"]),
    ],
    "Hosting Product Addon": [
        ("Addon", ["addon_name", "product"], ["price"]),
    ],
    "Hosting Product Group": [
        ("Group", ["product_group_name"], ["description"]),
    ],
    "Hosting Product Price": [
        ("Price", ["product", "billing_cycle"], ["currency", "price"]),
        ("Validity", ["effective_from"], ["effective_to"]),
    ],
    "Hosting Promo Code": [
        ("Code", ["code", "discount_type"], ["discount_value", "is_recurring"]),
        ("Rules", ["applies_to", "expiration_date"], ["usage_limit", "used_count", "product_group_restriction"]),
    ],
    "Hosting Promo Redemption": [
        ("Redemption", ["promo_code", "customer"], ["order", "discount_given"]),
    ],
    "Hosting Provider Account": [
        ("Provider", ["provider_name", "provider_type"], ["endpoint_url"]),
        ("Credentials", ["api_key"], ["api_secret"]),
    ],
    "Hosting Refund": [
        ("Refund", ["customer", "payment"], ["invoice", "refund_date"]),
        ("Amount", ["amount", "currency"], ["status"]),
        ("Details", ["reason"], ["idempotency_key", "reversal_of"]),
    ],
    "Hosting Service": [
        ("Service", ["customer", "status"], ["product", "billing_cycle"]),
        ("Order", ["order", "order_item"], ["subscription"]),
        ("Infrastructure", ["provider_account", "server_node"], ["ip_address", "domain"]),
        ("Upstream", ["upstream_service_id"], ["upstream_metadata"]),
        ("Lifecycle", ["provisioned_at", "suspended_at"], ["cancellation_requested_at", "terminated_at"]),
        ("Cancellation", ["cancel_at_period_end"], ["termination_reason"]),
        ("Reconciliation", ["last_reconciled_at", "reconciliation_status"], ["reconciliation_notes"]),
    ],
    "Hosting Service Modification Request": [
        ("Request", ["subscription", "service"], ["new_product", "status"]),
        ("Schedule", ["effective_mode", "effective_date"], ["proration_amount"]),
        ("Billing", ["invoice"], ["credit_transaction", "idempotency_key"]),
        ("Before", ["old_product", "old_amount"], ["old_billing_cycle", "old_product_snapshot"]),
        ("After", ["new_product_snapshot"], ["usage_snapshot"]),
        ("Risk", ["downgrade_warnings", "data_loss_acknowledged"], ["failure_reason"]),
        ("Result", ["applied_at"], ["events"]),
    ],
    "Hosting Subscription": [
        ("Subscription", ["customer", "product"], ["status", "billing_cycle"]),
        ("Billing", ["amount", "currency"], ["order"]),
        ("Period", ["current_period_start", "current_period_end"], ["next_renewal_date", "trial_end_date"]),
        ("Rules", ["billing_timezone", "renewal_lead_days"], ["grace_period_days"]),
        ("Retry", ["retry_count", "max_retries"], ["retry_backoff_minutes", "next_retry_at", "last_retry_at"]),
        ("Invoice", ["last_invoice"], ["last_error"]),
        ("Cancellation", ["cancel_at_period_end", "cancellation_mode"], ["cancellation_requested_at", "cancellation_effective_at"]),
        ("Exit", ["termination_scheduled_at", "data_purge_scheduled_at"], ["terminated_at", "suspend_reason"]),
        ("Scheduler", ["reinstatement_count"], ["locked_at", "locked_by"]),
    ],
    "Hosting Tax Rule": [
        ("Rule", ["tax_name", "country"], ["state_code", "gst_mode"]),
        ("Applies", ["product_group"], ["rate"]),
        ("Validity", ["effective_from", "effective_to"], ["is_active"]),
    ],
    "IPAM Allocation Log": [
        ("Allocation", ["ip_address", "action"], ["reference_doctype", "reference_name"]),
    ],
    "IPAM IP Address": [
        ("Address", ["ip_address", "subnet"], ["ip_version", "status"]),
        ("Allocation", ["allocated_to_doctype", "allocated_to_name"], ["allocated_at"]),
    ],
    "IPAM Subnet": [
        ("Subnet", ["subnet_name", "cidr"], ["ip_version", "gateway"]),
        ("Network", ["dns_servers"], ["vlan_id"]),
    ],
    "Monitoring Alert": [
        ("Alert", ["check", "status"], ["severity"]),
        ("Detail", ["detail"], []),
        ("Timeline", ["first_seen", "last_seen"], ["resolved_at"]),
    ],
    "Portal Audit Event": [
        ("Event", ["user", "endpoint"], ["status"]),
        ("Detail", ["detail"], ["at"]),
    ],
    "Provider Request Log": [
        ("Request", ["provider_account", "driver_type"], ["operation", "correlation_id"]),
        ("Call", ["action", "request_hash"], ["response_code"]),
        ("Data", ["request_summary"], ["response_summary"]),
        ("Result", ["error_type", "latency_ms"], ["logged_at"]),
    ],
    "Provisioning Attempt": [
        ("Attempt", ["operation", "attempt_no"], ["status"]),
        ("Timing", ["started_at", "finished_at"], ["duration_ms"]),
        ("Data", ["request_summary"], ["response_summary"]),
        ("Error", ["error_type"], ["error"]),
    ],
    "Provisioning Operation": [
        ("Operation", ["service", "subscription"], ["customer", "operation_type"]),
        ("State", ["status", "idempotency_key"], ["correlation_id"]),
        ("Provider", ["provider_account", "driver_type"], ["new_product"]),
        ("Retry", ["timeout_seconds", "max_retries"], ["retry_count", "next_retry_at"]),
        ("Error", ["error_type"], ["last_error"]),
        ("Meta", ["provider_metadata"], []),
        ("Timing", ["started_at", "finished_at"], ["attempt_count"]),
    ],
    "Reconciliation Result": [
        ("Check", ["service", "provider_account"], ["operation"]),
        ("State", ["local_state", "remote_state"], ["verdict"]),
        ("Report", ["details"], ["checked_at"]),
    ],
    "Resource Cleanup Task": [
        ("Task", ["service", "operation"], ["task_type", "status"]),
        ("Result", ["details"], ["completed_at"]),
    ],
    "Restore Request": [
        ("Request", ["backup", "service"], ["customer", "status"]),
        ("Auth", ["requested_by", "approved_by"], ["authorization_note"]),
        ("Result", ["failure_reason"], ["completed_at"]),
    ],
    "Scoped API Token": [
        ("Token", ["user", "prefix"], ["token_hash"]),
        ("Access", ["scopes"], ["expires_at"]),
        ("State", ["revoked"], ["last_used_at"]),
    ],
    "Security Audit Log": [
        ("Event", ["user", "action"], ["status"]),
        ("Detail", ["detail"], ["at"]),
    ],
    "Server Node": [
        ("Node", ["node_name", "provider_account"], ["datacenter", "node_type"]),
        ("Network", ["ip_address"], ["status"]),
        ("Capacity", ["cpu_cores_total", "ram_gb_total"], []),
        ("Maintenance", ["maintenance_mode"], ["maintenance_notes"]),
    ],
    "Service Action": [
        ("Action", ["service", "customer"], ["action_type", "status"]),
        ("Request", ["idempotency_key", "confirmed"], ["requested_by"]),
        ("Result", ["detail"], ["finished_at"]),
    ],
    "Service Addon": [
        ("Addon", ["service", "subscription"], ["customer", "addon"]),
        ("State", ["status", "price"], ["billing_cycle"]),
        ("Snapshot", ["product_snapshot"], []),
        ("Billing", ["current_period_end", "idempotency_key"], ["renewal_invoice"]),
        ("Result", ["failure_reason"], ["fulfilment_detail"]),
    ],
    "Service Backup": [
        ("Backup", ["policy", "service"], ["customer", "status"]),
        ("Run", ["started_at", "finished_at"], ["size_mb"]),
        ("Storage", ["storage_location", "retain_until"], ["failure_reason"]),
    ],
    "Service Storage Usage": [
        ("Usage", ["service", "customer"], ["measured_at"]),
        ("Meter", ["used_gb", "quota_gb"], ["overage_gb"]),
        ("Billing", ["overage_rate", "overage_invoice"], ["notified"]),
    ],
    "SSL Certificate": [
        ("Certificate", ["domain", "customer"], ["service", "status"]),
        ("Validation", ["validation_method", "validation_token"], []),
        ("Dates", ["issued_at", "expires_at"], ["auto_renew"]),
        ("Tracking", ["renewal_idempotency_key", "last_checked_at"], ["failure_reason"]),
    ],
    "Ticket Reference": [
        ("Ticket", ["ticket", "customer"], ["service"]),
        ("Links", ["order", "invoice"], ["domain"]),
        ("Meta", ["opened_by"], ["opened_at"]),
    ],
}

SKIP = {"Hosting Invoice Item", "Hosting Order Item", "Hosting Modification Event"}


def slug(label):
    return label.lower().replace(" ", "_")


def apply(path, name, spec):
    with open(path) as fh:
        doc = json.load(fh)
    existing = {f.get("fieldname") for f in doc.get("fields", [])}
    covered = [f for _, a, b in spec for f in a + b]
    real = [f for f in doc.get("field_order", []) if f in existing]
    missing = [f for f in real if f not in covered]
    extra = [f for f in covered if f not in existing]
    assert not missing, f"{name} fields not in spec: {missing}"
    assert not extra, f"{name} spec fields absent: {extra}"
    assert sorted(covered) == sorted(real), f"{name} coverage mismatch"

    new_fields = [f for f in doc["fields"] if f.get("fieldtype") not in ("Section Break", "Column Break")]
    order = []
    n = 0
    for label, col_a, col_b in spec:
        n += 1
        sfn = f"section_break_{slug(label)}"
        assert sfn not in existing, f"{name} clash {sfn}"
        new_fields.append({"fieldname": sfn, "fieldtype": "Section Break", "label": label})
        order.append(sfn)
        order.extend(col_a)
        if col_b:
            n += 1
            cfn = f"column_break_{n}"
            new_fields.append({"fieldname": cfn, "fieldtype": "Column Break"})
            order.append(cfn)
            order.extend(col_b)
    doc["fields"] = new_fields
    doc["field_order"] = order
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=4)
        fh.write("\n")
    return name


def main():
    paths = sorted(glob.glob(os.path.join(BASE, "*", "*.json")))
    by_name = {}
    for p in paths:
        with open(p) as fh:
            d = json.load(fh)
        if d.get("doctype") == "DocType":
            by_name[d["name"]] = p
    assert set(SPEC) - SKIP <= set(by_name), set(SPEC) - set(by_name)
    missing_spec = [n for n in by_name if n not in SPEC and n not in SKIP]
    assert not missing_spec, f"no spec: {missing_spec}"
    done = []
    for name, spec in SPEC.items():
        done.append(apply(by_name[name], name, spec))
    print(f"layouts applied: {len(done)}")


if __name__ == "__main__":
    main()
