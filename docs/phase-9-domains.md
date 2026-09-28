# Phase 9 — Domains, DNS, SSL, Backups, and Add-ons

Date: 2026-09-28. All changes are additive. No existing DocType,
field, hook, API, or status value was modified (two new transition
edges were appended to new Phase 9 controllers only, before merge).

## 1. Preserved behavior and conventions

- Billing still keys invoices and ledger rows off User (Phases 4-7
  convention). New engines resolve the billable user through
  `notifications.billable_customer` (Hosting Customer primary user,
  else the value itself).
- Fulfilment failures reuse Phase 8 `Resource Cleanup Task` records.
- Scheduler hook lists only append; existing daily jobs are kept.

## 2. Records (all new)

- `Domain Registrar Account`: provider (Simulated/Custom/Namecheap/
  Cloudflare/GoDaddy/NameSilo), endpoint, credential *reference*
  (secrets refused in validate), supported TLDs, auto-renew default,
  active flag.
- `Hosting Domain`: unique lowercase domain name, customer, service,
  registrar account, lifecycle (Pending Registration, Active,
  Transfer Pending, Expired, Grace Period, Redemption, Cancelled,
  Terminated), transfer status, registration/expiry dates,
  auto-renew, nameservers, Password-type auth code, registration and
  renewal idempotency keys, reminder stage tracking, failure reason.
  Cancelled registrations may return to Pending Registration for
  staff retry; nothing else regresses.
- `Hosting DNS Record`: domain, type (A/AAAA/CNAME/MX/TXT/SRV/NS/
  CAA), host, value, TTL (min 60), priority (required for MX/SRV),
  Active/Inactive. Apex CNAME refused.
- `SSL Certificate`: domain, customer, installation-target service,
  lifecycle (Pending Validation, Active, Renewal Pending, Expired,
  Failed, Revoked, Cancelled), validation method, token, issued/
  expiry dates, auto-renew, last check, failure reason. Failed rows
  may revalidate directly to Active.
- `Backup Policy`: service scope (customer auto-filled), frequency
  (Manual/Daily/Weekly/Monthly), retention count and days, storage
  location, enabled, last/next run.
- `Service Backup`: policy, service, lifecycle (Pending, In
  Progress, Completed, Failed, Expired, Deleted), timing, size,
  location, retain-until, failure reason.
- `Restore Request`: backup, service, lifecycle (Pending, Approved,
  In Progress, Completed, Failed, Rejected), requester, approver,
  authorization note. Only Completed backups accepted; executes
  only from Approved.
- `Service Addon`: service, subscription, customer, catalog addon,
  lifecycle (Pending, Active, Suspended, Cancellation Pending,
  Cancelled, Failed), price, cycle, frozen product snapshot,
  period end, unique idempotency key, renewal invoice, fulfilment
  detail.
- `Service Storage Usage`: service, measured_at, used/quota GB,
  overage derived in validate, rate, overage invoice, notified flag.

## 3. Engines

- `domains.py`: `BaseRegistrarDriver` plus in-memory simulated
  driver (availability, register, renew, transfer, nameservers)
  with fault injection; failures reuse the Phase 8
  `ProvisioningError` taxonomy. Register is idempotent and refuses
  names already managed; failures park as Cancelled with reason and
  staff `retry_domain_registration` recovers. Renewals invoice
  first (idempotent key per domain/expiry/years) and extend at the
  registrar only once Paid. Transfers return to Active with a Failed
  transfer flag on error. `process_domain_renewals` (daily) sends
  one reminder per 30/14/7/1-day stage, raises auto-renew invoices
  inside 7 days and renews paid ones, expires past-due domains, and
  progresses Expired to Grace Period to Redemption to Terminated on
  a 30/30/30-day ladder.
- `certificates.py`: request issues a challenge token; DNS
  validation genuinely checks the local TXT record, HTTP is
  simulated; success activates for 90 days. Installation targets
  must belong to the same customer. `monitor_certificates` (daily)
  auto-renews inside 30 days, records failed renewals with alerts,
  expires past-due rows, and fails validations stale over 7 days.
- `backups.py`: `run_backup` executes per policy with retention
  dates; `run_due_backups` schedules enabled policies;
  `enforce_retention` expires past-retain rows, purges long-expired
  ones, and trims over-count keeps. Restores are two-step:
  request (any creator) then staff approve/reject; execution
  failures return to Failed for re-approval. `record_storage_usage`
  derives overage and notifies; `process_storage_overage` invoices
  each overage snapshot exactly once.
- `addons.py`: `provision_addon` snapshots the catalog row and
  fulfils idempotently; fulfilment faults mark Failed plus a cleanup
  task, and staff `retry_addon` recovers. `renew_addon` invoices
  first and extends on payment; `process_addon_renewals` (daily)
  invoices due addons and closes end-of-period cancellations.
  `cancel_addon` supports Immediate and End of Period;
  `sync_addons_for_service` mirrors suspension/termination.
- `notifications.py`: shared Comment audit plus best-effort email
  via the customer's primary user; never raises.

## 4. Tests (128 pass on beaverbill.localhost)

- New `test_domains_ssl_backups.py`: 28 pass. Registration,
  idempotency, duplicates, name validation, registrar failure plus
  retry, paid-gated renewal with invoice idempotency, transfer
  success/failure, nameservers, DNS CRUD and guards, reminders,
  auto-renew, full expiry ladder, DNS challenge validation,
  install-target ownership, renewal plus failed renewal, monitor
  renew/expire/stale, backup run success/failure, retention trim,
  restore approve/reject/retry, restore guards, overage computed
  and invoiced once, addon provision/idempotency/failure/retry,
  renewal, both cancel modes, service sync.
- Regression: 10 billing, 11 catalog, 8 customer-service,
  13 gateway, 8 infra, 11 IPAM, 11 modifications, 10 subscription,
  18 provisioning, all OK.
- Commands: `bench --site beaverbill.localhost migrate`,
  per-module `run-tests`, `python3
  scripts/beaverbill_phase_check.py phase-9`.

## 5. Gaps recorded honestly

- Browser evidence for domain/SSL/backup/addon screens: not
  captured (no browser binary in this environment).
- Registrar, CA, and storage backends are simulated; no live
  registrar/CA traffic. Sandbox tests remain Phase 14 work.
- Evidence: `docs/phase-9-domains.md`,
  `docs/evidence/phase-9-baseline.json`.
