# Beaver Bill Architecture (No ERPNext)

Beaver Bill is a self-contained Frappe Framework app. It owns its
customers, catalog, orders, invoices, payments, credits,
subscriptions, services, IPAM, provisioning, domains, SSL, backups,
portal, tickets bridge, audit, monitoring, and release records.
ERPNext is never imported, required, or referenced by code; the
phase gate scans every release for it.

## 1. Module map

| Layer | Modules | Owns |
|---|---|---|
| Catalog | `pricing`, `patches.phase2_*` | groups, products, versioned prices, tax rules, promos + redemption ledger |
| Customers | `permissions`, `backfill_services` | `Hosting Customer`, contacts, groups, tax profiles, services |
| Billing | `billing` | orders, invoices (+items, snapshots, PDFs), payments, allocations, refunds, credit/debit notes, wallet ledger |
| Gateways | `gateways`, `webhooks` | gateway/method records, intents, HMAC webhook intake, idempotent apply, replay, reconciliation |
| Subscriptions | `subscriptions`, `subscription_lifecycle`, `subscription_support` | renewal scheduler, dunning, grace, suspension, cancellation, reinstatement, purge |
| Modifications | `modifications`, `modification_apply` | proration, snapshots, approvals, resize compensation |
| Provisioning | `provisioning`, `provisioning_drivers` | operation queue, retries by error type, compensation, reconciliation, cleanup |
| Domains/SSL/backups | `domains`, `certificates`, `backups`, `addons` | registrar lifecycle, DNS, cert validation/install, backup policies/retention/restores, addons |
| Portal | `portal/*`, `www/beaverbill.py`, `frontend/` | session APIs, ownership guard, rate limits, audit, frappe-ui SPA |
| Helpdesk | `helpdesk_sync` | same-site mirrors, ticket bridge, SLA snapshot, mail health |
| Security | `security`, `security_tokens`, `permissions` | role matrix, scoped tokens, sessions, throttling, validators, audit |
| Observability | `monitoring`, `reconciliation` | 13 checks, 8 pair runners, deduplicated alerts, staff dashboard |
| Release | `deployment`, `scripts/deploy_*`, `scripts/beaverbill_snapshot_*` | smoke, scheduler validation, version manifests, backup drill |

56 non-table DocTypes in `beaverbill/beaverbill/doctype/`; portal
audit, security audit, monitoring alerts, and scoped tokens are
first-class records alongside business data.

## 2. Request path

```
browser (frappe-ui SPA, CSRF token)
  → /api/method/beaverbill.beaverbill.portal.* (session auth)
  → portal.guard (rate limit → ownership → audit)
  → engine module (billing, subscriptions, provisioning, …)
  → DocType validate() (state machines, SSRF/shape guards)
  → permission hooks (row-level ownership, staff separation)
```

Webhooks skip sessions and use HMAC signatures plus idempotency
keys. Desk access is staff-only with row-level conditions.

## 3. State machines (server-enforced)

- Order: `Draft → Confirmed → Payment Pending → Paid →
  Processing → Completed → Cancelled`.
- Invoice: `Draft → Issued → Partially Paid → Paid → Overdue →
  Cancelled → Written Off`.
- Payment: `Created → Authorized → Captured → Failed → Refunded
  → Partially Refunded → Chargeback`.
- Subscription: `Trial → Active → Renewal Pending → Payment
  Failed → Grace Period → Suspended → Cancellation Pending →
  Terminated → Archived`.
- Service: `Pending → Provisioning → Active → Modification
  Pending → Suspended → Cancellation Pending → Terminated →
  Archived`.
- Provisioning operation: `Pending → Queued → Running →
  Succeeded → Failed → Retrying → Manual Review → Compensated`.

Illegal jumps throw `ValidationError`; destructive unknowns park
in `Manual Review` instead of retrying blind.

## 4. Money flow

Catalog price → cart quote → order snapshot → invoice snapshot →
gateway intent → signed webhook → allocation → Paid. Refunds,
credit notes, and chargebacks move through the wallet ledger, so
`ledger_mismatches` and `invoice_outstanding` stay empty on a
healthy site. Nothing is ever edited in place: corrections are
new documents linked to their source.

## 5. Provisioning flow

Portal or scheduler queues an idempotent operation → capacity and
driver resolution → attempt with timeout → classified error
(transient, rate-limited, capacity, permanent, unknown) → retry,
compensation with cleanup tasks, or manual review → service state
sync with correlation IDs and secret-free request logs.

## 6. Scheduler (daily)

Renewals, due modifications, queued operations, domain renewals,
certificate monitoring, addon renewals, backups, retention,
storage overage, helpdesk sync, monitoring cycle, reconciliation
cycle — all idempotent and lock-guarded for overlapping runs.

## 7. Integration contracts

- `frappe/payments`: gateway adapter layer only; money truth
  stays in Beaver Bill records.
- `frappe/helpdesk`: same-site native documents; Beaver Bill
  customers/contacts are canonical, HD rows are mirrors; agent
  internals (assignment, SLA policy) stay helpdesk-owned.
- `frappe-ui`: session + CSRF, no ERPNext routes or DocTypes in
  the SPA (verified in the Phase 11 gate).
- Providers: versioned driver contract with legacy-signature
  compatibility; simulated drivers for offline development.

## 8. Why no ERPNext

Beaver Bill needs hosting semantics ERPNext lacks (services,
IPAM, provisioning, consoles, domains, dunning with service
sync) and must stay installable on a lean Frappe site. Reusing
ERPNext customers, invoices, or payments would couple billing to
an accounting model we do not use and force every deployment to
carry it. The boundary is enforced by convention (this doc),
by tests (`test_release_health` pins `required_apps`), and by
the release gate (ERPNext import/dependency scan).
