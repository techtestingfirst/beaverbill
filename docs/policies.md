# Beaver Bill Business Policies

Version: Phase 17 (2026-09-28). Each policy ends with an
**Enforcement** note: `automatic` means the code enforces it;
`procedural` means staff follow it. Where the code enforces a rule,
the module is named so the claim can be checked.

## 1. Terms of Service

- Accounts are for the named customer (individual or company) on
  `Hosting Customer`. One login owns one customer record through
  `primary_user`; sharing logins is not supported.
- Services are provided against paid orders and active
  subscriptions. Prices are locked per order/invoice snapshot, not
  retroactively changed.
- We may suspend for non-payment, abuse, or legal cause after the
  dunning and suspension rules below. Either party may terminate
  with the cancellation rules below.
- **Enforcement**: procedural, with automatic suspension,
  cancellation, and purge flows.

## 2. Acceptable Use

- No spam, phishing, malware, botnets, crypto mining on shared
  plans, or traffic that degrades other tenants.
- No unlawful content; no credential sharing; no circumventing
  rate limits, login throttling, or access controls.
- First violation: warning plus case ticket. Repeat or severe
  abuse: service suspension, then termination with the 30-day
  purge window. Illegal activity is reported to authorities.
- **Enforcement**: procedural (abuse tickets), with automatic
  throttling (`security_tokens`), rate limits (`portal.guard`),
  and suspension flows.

## 3. Privacy and Data Retention

- We store: account and contact data, consent timestamps
  (`consent_terms`, `consent_marketing`, `consent_datetime`),
  orders, invoices, payments (token references only — never card
  numbers, CVV, or PAN), service metadata, tickets, and audit
  events. Email verification state is recorded per customer.
- Secrets (provider keys, webhook secrets, auth codes) use
  encrypted `Password` fields and never appear in logs, hashes,
  or evidence (`security.scrub_*`, driver `safe_summary`).
- Marketing contact needs explicit opt-in; withdrawing consent
  stops marketing mail but not billing or security notices.
- Retention: active records live while the account is open;
  terminated services purge after 30 days
  (`PURGE_AFTER_TERMINATE_DAYS`); backups expire per Backup Policy
  (default 7 copies / 30 days); audit and financial rows are kept
  for tax and dispute windows and then archived on request where
  the law allows.
- **Enforcement**: automatic capture and encryption; procedural
  marketing and erasure handling.

## 4. Refund Policy

- New-service mistakes (wrong plan, immediately reported):
  end-of-period cancel plus unused-period credit, or immediate
  cancel with prorated credit to the wallet.
- Gateway-confirmed duplicate charges are refunded in full
  (`process_refund`, idempotent per event).
- Used service time, consumed bandwidth/storage, domain
  registrations, and installed SSL validation work are not
  refundable once delivered.
- Refunds post as ledger-backed wallet credit by default and to
  the original payment method on request to billing staff.
- Chargebacks freeze the disputed amount while the gateway case
  runs; abuse of chargebacks triggers section 15.
- **Enforcement**: automatic (`billing.process_refund`,
  `create_credit_note`); windows are procedural.

## 5. Cancellation Policy

- Default is end-of-period: the subscription enters
  `Cancellation Pending` and runs to `current_period_end`
  (`subscription_lifecycle.cancel_subscription`).
- Immediate cancellation terminates at once, credits the unused
  period to the wallet, and schedules data purge 30 days out.
- Services move `Active → Cancellation Pending → Terminated →
  Archived`; direct jumps are rejected by the state machine.
- Domain and SSL cancellations stop renewals; registered names
  follow the registry grace rules, not ours.
- **Enforcement**: automatic transitions and credits.

## 6. Upgrade and Downgrade Policy

- Upgrades and downgrades run through modification requests with
  product snapshots and proration (`modifications`).
  `Immediate` bills the prorated difference at once; `Next Cycle`
  applies at renewal without an invoice.
- Downgrades that shrink disks, databases, or included limits
  need explicit data-loss acknowledgement; usage checks block
  downgrades below current consumption.
- Failed resizes compensate rather than strand: the request
  stays auditable with an operation history and idempotency key.
- **Enforcement**: automatic.

## 7. Suspension Policy

- Dunning: up to 4 retries (`max_retries` default) with 4-hour
  backoff, then a 7-day grace period (`grace_period_days`
  default), then suspension. Renewal invoices go out 3 days
  early (`renewal_lead_days` default); all three are
  per-subscription fields staff can tighten but not bypass.
- Suspension powers services down and syncs linked services;
  data is kept. Reinstatement returns the subscription to
  `Active` from `Payment Failed`, `Grace Period`, `Suspended`,
  or `Cancellation Pending` (`reinstate_subscription`, staff).
- **Enforcement**: automatic (`subscriptions`,
  `subscription_lifecycle`).

## 8. Termination and Data-Purge Policy

- Terminated services keep data for 30 days, then purge jobs
  remove service data (`data_purge_scheduled_at`).
- Backups of terminated services expire with their Backup Policy
  instead of being deleted at once, so recent restores stay
  possible inside the window.
- After purge, recovery is impossible; customers are notified at
  termination and at purge scheduling.
- **Enforcement**: automatic scheduling; purge execution is a
  staff-visible job.

## 9. Backup and Restore Policy

- Backup Policies default to daily runs keeping 7 copies for 30
  days; per-service policies override both numbers.
- Retention jobs expire, then purge, old backups automatically
  (`run_due_backups`, `enforce_retention`).
- Restores need an explicit customer request plus staff approval
  (`request → approve → execute`); restores overwrite target
  data and are confirmed twice in the portal.
- Site-level disaster recovery keeps 30 days of encrypted daily
  site backups (RPO 24 h, RTO 2 h full rebuild / 30 min
  database-only); see `docs/phase-16-release.md`.
- **Enforcement**: automatic schedules and approval gates.

## 10. Domain-Renewal Policy

- Domains default to `auto_renew`; renewal invoices go out
  before expiry and the registrar renews within 7 days of expiry
  once paid (`AUTO_RENEW_WITHIN_DAYS`).
- Renewals cost USD 15 per year (`RENEWAL_PRICE`,
  `RENEWAL_CURRENCY`); multi-year renewals multiply accordingly.
- Expired names enter a 30-day grace period (`GRACE_DAYS`) with
  reminders; after grace the registry may delete the name and we
  cannot recover it.
- Transfers need a valid auth code and re-register one year at
  the registry.
- **Enforcement**: automatic (`domains`).

## 11. SSL Policy

- Certificates are domain-validated (DNS challenge), valid 90
  days (`CERT_VALIDITY_DAYS`), and monitored daily.
- Renewal is attempted automatically before expiry; failed
  renewals notify the customer and retry with a fresh challenge
  token (`monitor_certificates`, `renew_certificate`).
- Installation targets one owned service; cross-customer
  installation is rejected.
- **Enforcement**: automatic (`certificates`).

## 12. Resource Overage Policy

- Storage, backup, and addon usage is metered per service.
  Overage bills per measured GB at the rate configured on the
  usage snapshot (`overage_rate`), invoiced idempotently once
  per snapshot (`process_storage_overage`).
- Overage never auto-suspends; sustained overage triggers a
  notice and an upgrade recommendation instead.
- Disputed meter readings are re-checked against provider
  reports through reconciliation before adjustment.
- **Enforcement**: automatic metering and invoicing.

## 13. Maintenance Policy

- Nodes and gateways have `maintenance_mode`. Maintenance
  suspends new provisioning and payments on that target;
  in-flight operations finish or park with retries.
- Customer-impacting maintenance is announced in advance except
  emergency security work, which is announced after.
- **Enforcement**: automatic mode checks
  (`provisioning._capacity_check`, gateway outage handling);
  announcements are procedural.

## 14. SLA Policy

- Ticket priorities (Low/Medium/High/Urgent) map to helpdesk
  priorities with response targets of 24 h / 8 h / 4 h / 1 h on
  business days. These are targets, reviewed quarterly against
  `response_by`/`resolution_by` snapshots (`ticket_sla`).
- Platform targets: portal availability 99.5 % monthly excluding
  announced maintenance; webhook processing 15 min; renewal
  invoicing 3 days before expiry.
- SLA failures are credited on request, not automatically.
- **Enforcement**: targets are procedural; measurement fields
  are automatic.

## 15. Chargeback and Abuse Policy

- A gateway chargeback opens a `Chargeback` refund record and a
  ledger entry, freezes the disputed amount, and notifies the
  customer with the case reference.
- Confirmed friendly fraud (service consumed, then charged back)
  leads to immediate suspension and, on repeat, termination plus
  a block on new accounts with the same payment identity.
- Brute-force, scraping, and webhook forgery attempts hit login
  throttling (5 misses → 15-minute lock), per-endpoint rate
  limits, and HMAC rejection with audit rows; staff revoke
  sessions and tokens on confirmed compromise.
- **Enforcement**: automatic (`webhooks`, `security_tokens`,
  `portal.guard`); account actions are procedural.

## 16. Wallet-Credit Expiration Policy

- Wallet credits are ledger-backed (`Customer Credit
  Transaction`), applied to invoices automatically or on
  request, and itemized per source document.
- Credits do not expire and are not transferable between
  customers. They are not cash and cannot be withdrawn, only
  applied to Beaver Bill invoices or refunded to the original
  method under section 4.
- **Enforcement**: automatic (no expiry exists in code, by
  policy).
