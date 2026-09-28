# Phase 3 — Customer Accounts and Hosting Service Model

Date: 2026-09-28. Beaver Bill now owns its customer records; no ERPNext
`Customer` is used or referenced. All changes are additive to earlier phases.

## 1. Customer source of truth

- `Hosting Customer` is the source of truth: individual/company types,
  billing + technical contacts (via `Hosting Customer Contact`), customer
  group link, tax profile link, status (Prospective/Active/Suspended/
  Closed), locale/timezone, email + identity verification flags, terms/
  marketing consent with timestamp.
- `Hosting Customer Group`: named groups with descriptions.
- Validation: companies need `company_name`; primary user must exist;
  consent timestamp auto-set when terms are accepted.
- No migration of `User` records: existing order/invoice/subscription
  `customer` (User) links are untouched; `Hosting Customer.primary_user`
  bridges them.

## 2. Hosting Service

- Links: customer (required), product, order, order-item row, subscription,
  provider account, server node, IP address, domain placeholder (Phase 9
  record link), upstream service ID + metadata JSON.
- Lifecycle fields: provisioned/suspended/cancellation-requested/
  terminated timestamps (auto-set on transition), cancel-at-period-end,
  termination reason, reconciliation status/notes/timestamp.
- State machine enforced in `validate`:
  Pending to Provisioning/Cancellation Pending; Provisioning to
  Active/Terminated; Active to Modification Pending/Suspended/Cancellation
  Pending; Modification Pending to Active/Suspended; Suspended to
  Active/Cancellation Pending/Terminated; Cancellation Pending to
  Terminated/Active; Terminated to Archived.
- `track_changes` enabled for audit history.

## 3. Ownership and permissions

- Roles: Hosting Admin full; Hosting Support create/read/write (no delete)
  on Customer, Contact, Service. Hosting Customer role gets read rows.
- Enforcement (controllers grant nothing; the framework only lets hooks
  deny, verified in `frappe/permissions.py`):
  `permission_query_conditions` limits lists to owned records, and
  `has_permission` hooks (`check_service_ownership`,
  `check_customer_ownership`) deny non-owned docs. Staff pass through to
  role permissions.
- Record-level customer ownership for orders/invoices arrives with portal
  APIs (Phase 10); infra/customer-model isolation is tested here.

## 4. Backfill

- `beaverbill/beaverbill/backfill_services.py`: `preview_backfill()` reports
  would-create/duplicates/orphans/missing-customers;
  `execute_backfill(dry_run=True)` writes Pending services only with
  `dry_run=False`. Duplicate-safe across reruns (subscription, order-item,
  and in-run order+product guards). Missing customers and order-less
  subscriptions are reported, never invented.
- Staging execution happens through the same function after dry-run review;
  this site had no production data to migrate.

## 5. Pricing integration

- `Hosting Customer Tax Profile` gained an optional `customer` link;
  `get_tax_profile`/`calculate_price` resolve by customer record first,
  then by user. User-keyed profiles keep working.

## 6. Tests (54 pass on beaverbill.localhost)

- `bench --site beaverbill.localhost run-tests --app beaverbill`: 38
  integration + 16 pre-existing, all OK.
- New `test_customer_service` (8): company validation, consent timestamp,
  contact CRUD + email validation, service lifecycle/timestamps/illegal
  moves, ownership (own-read, cross-deny, write-deny, staff-read, list
  isolation), backfill preview/execute/idempotency/duplicates, orphan and
  missing-customer reporting, tax via customer link.

## 7. Gaps recorded honestly

- Browser evidence for customer/service screens: not captured (no browser
  binary in this environment).
- Evidence: `docs/phase-3-customer.md`,
  `docs/evidence/phase-3-baseline.json`.
- Commands: `bench --site beaverbill.localhost migrate`,
  `bench --site beaverbill.localhost run-tests --app beaverbill`,
  `python3 scripts/beaverbill_phase_check.py phase-3`.
