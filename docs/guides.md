# Beaver Bill Guides

## 1. Customer Guide

### Sign up and verify

1. Call `signup` (full name, email, password) from `/beaverbill`.
   The account is created with the `Hosting Customer` role and a
   verification mail with a 24-hour token.
2. Follow the link (`verify_email`) or `resend_verification` for a
   fresh token. Verified customers can use every portal feature.

### Buy and pay

1. Browse `list_products` / `get_product`; configure options and
   addons; check coupons with `validate_coupon`.
2. `cart_add`, optionally `cart_coupon`, then `checkout` with your
   own idempotency key (safe to retry: repeats return
   `duplicate_request`).
3. Pay with `pay_invoice` (gateway + saved method or new token
   reference). Track with `payment_status`; invoices and PDFs come
   from `list_invoices` / `get_invoice` / `invoice_pdf`.
4. Never paste card numbers anywhere: only gateway token
   references are stored (`token_reference`).

### Run services

- `service_dashboard` lists services and subscriptions;
  `service_detail` shows status, IP, product, and operations.
- `power` with `reboot`, `poweroff`, or `poweron` queues a
  tracked operation. `console_url` issues a 15-minute single-use
  console ticket redeemed once with `console_ticket`.
- `password_reset` and `os_reinstall` need confirmation plus an
  idempotency key; reinstall additionally needs the data-loss
  acknowledgement. `change_plan` starts upgrades/downgrades.
- Domains, DNS, certificates, backups, restores, and addons live
  under `my_domains`, `my_certificates`, `my_backups`, and
  `my_addons`. Restore requests need staff approval.
- Tickets: `create_ticket`, `ticket_detail` (your messages plus
  agent replies; internal notes stay hidden), `ticket_reply`.

## 2. Administrator Guide

- Customers: `Hosting Customer` is the source of truth, keyed by
  `primary_user`. HD customers/contacts are synced mirrors, never
  edited directly (`helpdesk_sync`).
- Money: invoices snapshot prices; allocate with
  `allocate_payment`; refunds/credit/debit notes keep the ledger;
  mismatches surface in `credit_ledger_mismatch` and
  `invoice_outstanding` reports plus the Phase 15 checks.
- Subscriptions: retry with `retry_subscription_payment`,
  override states explicitly, reinstate from failed/grace/
  suspended/cancellation-pending, cancel immediate or
  end-of-period. Renewals run on the scheduler with locking.
- Provisioning: `retry_operation` / `cancel_operation` on stuck
  rows; `Manual Review` rows need a human; cleanup tasks clear
  orphaned provider resources.
- Webhooks: failed events replay with `replay_payment_event`;
  never edit stored payloads.
- Security: issue/revoke scoped tokens, revoke sessions on
  compromise, rotate provider credentials (logged, secrets never
  shown), watch `Security Audit Log` and the health dashboard.
- Helpdesk: `sync_report` shows failures and mail health;
  `retry_sync` requeues.

## 3. Provider Setup Guide

- Create a `Hosting Provider Account` (Hosting Admin only):
  name, type (`Hetzner Cloud`, `OVHcloud`, `cPanel/WHM`,
  `DirectAdmin`, `Proxmox VE`, `Custom`, dedicated IPAM driver),
  endpoint URL, API key/secret (encrypted at rest).
- Endpoint URLs must be public `http(s)` on ports 80/443 —
  private hosts, metadata addresses, and odd ports are rejected
  (SSRF guard). Console URLs additionally need a driver with
  `get_vnc_console` (Proxmox VE ships one).
- Capacity: attach services to a `Server Node`; mark
  `maintenance_mode` to drain it. IPAM subnets auto-create host
  rows on insert; never hand-insert addresses.
- Drivers implement the v2.0 contract (`provision`, `suspend`,
  `unsuspend`, `terminate`, `resize`, optional `reboot`,
  `get_vnc_console`, `describe`). Unknown outcomes must raise
  instead of guessing, so destructive retries stay safe.
- Rotate credentials on schedule and on staff changes
  (`rotate_provider_credential`); the rotation itself is audit
  logged without secret material.

## 4. API Reference (portal, session auth)

Auth rides the Frappe session cookie (or API key); every call
resolves the caller's `Hosting Customer`. Guests reach only
`signup`, `verify_email`, `resend_verification`, and the gateway
webhook URL.

- Account: `session_status`, `get_profile`, `update_profile`,
  `list/add/update/delete_contact`.
- Catalog/cart/orders: `list_products`, `get_product`,
  `validate_coupon`, `get_cart`, `cart_add/remove/clear/coupon`,
  `checkout`, `list_orders`, `get_order`.
- Billing: `list_invoices`, `get_invoice`, `invoice_pdf`,
  `pay_invoice`, `payment_status`, `list_gateways`,
  `list/add/remove_payment_methods`.
- Services: `service_dashboard/detail/usage`, `power`,
  `console_url/ticket`, `password_reset`, `os_reinstall`,
  `change_plan`.
- Assets: `my_domains`, `domain_detail`, `dns_add/remove`,
  `my_certificates`, `request_certificate`,
  `my_backups`, `request_restore`, `restore_status`,
  `my_addons`, `order_addon`, `cancel_addon`, `storage_usage`.
- Support: `create_ticket`, `ticket_list/detail/reply`.
- Staff: `release_status`, `health_dashboard`, `sync_report`,
  `retry_sync`, `replay_payment_event`, `retry_failed_payment`,
  `retry_operation`, `issue/revoke_scoped_token`,
  `revoke_user_sessions`, `rotate_provider_credential`.

Rate limits apply per endpoint; denials and errors are audited.
Destructive actions need explicit confirmation flags and
idempotency keys — retries with the same key return the original
record instead of doubling the action.

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Login required` / `No hosting customer` | guest or role-less login | sign up / ask staff to link the user |
| `Rate limit exceeded` | too many calls in 60 s | wait and retry with backoff |
| `Too many failed logins` | 5 misses in 15 min | wait 15 min or ask staff to revoke sessions |
| `Invalid webhook signature` | wrong secret or body rewritten | compare gateway secret; replay after fixing |
| `Amount differs from payment` | currency/rounding drift | void and re-issue intent for the exact total |
| Operation `Failed`, retryable | transient provider error | `retry_operation`; check provider status |
| Operation `Manual Review` | unknown outcome, destructive op | verify at the provider, then staff override |
| Domain stuck `Pending` | registrar fault | `retry_domain_registration`; registry faults clear |
| Certificate `Failed` validation | missing TXT record | add `_acme-challenge` TXT, re-validate |
| Restore stays `Pending` | needs staff approval | approve in desk, then it executes |
| Ticket reply not visible | internal agent note | agent notes stay internal by design |
| Invoice `Overdue` after paying | webhook not yet processed | check `unprocessed_webhooks`; replay the event |
| `Console ticket invalid/expired` | 15 min passed or already used | issue a fresh ticket |

## 6. Incident Runbooks

### Failed payments spike (`mon:failed_payments` Critical)

1. Open the health dashboard; list events in `gateway_reconciliation`.
2. Check gateway `maintenance_mode` and provider status page.
3. Replay failed events once providers recover; use
   `retry_failed_payment` for stuck rows past `max_retries`.
4. If the gateway itself is down, postpone dunning via subscription
   overrides and notify customers.

### Stuck provisioning (`mon:provisioning` fail)

1. List `Provisioning Operation` rows `Queued/Running` older than
   2 h with their attempts and request logs.
2. Retry transient errors; cancel and re-queue poisoned rows.
3. For `Manual Review`, confirm provider-side truth, reconcile the
   service, then close the row — never blind-retry terminate.
4. Drain the node (`maintenance_mode`) if capacity or rate limits
   are the cause.

### Domain or certificate expiry wave

1. `process_domain_renewals` / `monitor_certificates` output shows
   what automation already tried.
2. Funded customers auto-renew; chase unpaid renewal invoices.
3. Re-add DNS challenges for failed validations; use registrar
   retry actions for faulted registrations.

### Backup failures

1. Check `failure_reason` on the `Service Backup` row and node
   disk/credentials.
2. Re-run the policy; expired retention rows are normal noise.
3. Restore requests stay gated on approval throughout.

### Helpdesk sync backlog

1. `sync_report`: failures carry error taxonomy and attempts.
2. `retry_sync` requeues; fix mapping (status/priority/team) or
   mail accounts first if those are the cause.

### Security incident (suspected compromise)

1. `revoke_user_sessions` for affected logins; revoke their scoped
   tokens; rotate provider credentials they could reach.
2. Read `Security Audit Log` and `Portal Audit Event` for the
   window; preserve evidence before cleanup.
3. Force password resets; lift the login-throttle lock only after
   the cause is found.

### Disaster recovery

Follow `docs/phase-16-release.md` section 6: decrypt the latest
verified backup set, restore, migrate, run `release_status`
smoke, compare canary counts. RPO 24 h, RTO 2 h (30 min
database-only).
