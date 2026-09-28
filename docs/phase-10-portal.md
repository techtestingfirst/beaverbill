# Phase 10 — Customer Portal APIs

Date: 2026-09-28. All changes are additive except two deliberate,
backward-compatible permission extensions (customers may now update
their own profile record, and Failed certificates/revalidation plus
Cancelled domain retries were already added in Phase 9).

## 1. Authentication and session behavior (Frappe-native)

- No custom auth: every endpoint rides the Frappe session cookie
  (or API key/token) and resolves the caller through
  `Hosting Customer.primary_user`. Guests and logins without a
  linked customer are denied (`portal.session_status` reports
  user, roles, and linked customer).
- Portal use requires the `Hosting Customer` role; staff roles
  bypass ownership but every call is still audited.

## 2. Ownership, rate limits, audit

- `portal/guard.py`: `portal_customer`, `may_access_customer`,
  per-record `own_*_or_throw` loaders, sliding-window
  cache-backed `check_rate` (`RateLimitExceededError`), append-only
  `audit`, and the `portal_endpoint` decorator (rate limit, then
  audit OK/Denied/Rate Limited/Error while re-raising).
- Row-level security in `permissions.py` + `hooks.py` (additive
  maps): query conditions and `has_permission` checkers for
  orders, contacts, domains, DNS (ownership resolves via the
  linked domain), certificates, backups, restores, addons,
  actions, usage, invoices, payments, subscriptions, and
  notifications. Customers see and touch only their own rows.
- DocType grants for the customer role (additive rows only):
  order create/read/write, contact full CRUD, domain/DNS
  create/read/write, certificate/addon-action create/read,
  addon/invoice/payment write-back for checkout and payment
  flows, catalog read, subscription read, own-profile write.
- New records: `Portal Audit Event` (immutable), `Customer
  Notification` (mirrored by `notifications.notify`, so every
  engine notice now also feeds the portal), `Service Action`
  (Pending/In Progress/Completed/Failed with unique
  idempotency key).

## 3. Endpoint inventory (`beaverbill/beaverbill/portal/`)

- `account`: session_status, get/update profile, contact CRUD.
- `catalog`: product list (with FX conversion) and detail
  (options, addons, specs, live versioned price), dry-run coupon
  validation (never consumes).
- `orders`: cache-backed cart (add/remove/clear/coupon with live
  pricing), idempotent checkout (prices each line, redeems the
  coupon against the billable User, creates order Draft to
  Confirmed to Payment Pending plus an Issued invoice, clears
  the cart), order list/detail.
- `billing` (portal): invoice list/detail/PDF, server-side
  payment intent creation (idempotent), local payment status
  with invoice-ownership fallback.
- `services`: dashboard, detail (recent operations, addons),
  usage (reported plus storage snapshots), power
  (reboot/poweroff/poweron executed synchronously through the
  Phase 8 queue), single-use expiring console tickets (15 min
  TTL, session-bound), confirmed idempotent password reset,
  double-confirmed idempotent OS reinstall, upgrade/downgrade
  via the Phase 7 modification engine.
- `assets`: owned domains/DNS/SSL/backups/addons/storage;
  certificate ordering, DNS add/remove, restore requests
  (approval still staff-gated), addon order/cancel.
- `support`: HD Ticket bridge (create/list/detail/reply with
  attachment ownership validation, raised_by attribution,
  `via_customer_portal` flag) plus the notification feed
  (list/unread count/mark read).
- Ticket writes run in an Administrator context because
  helpdesk `after_insert` hooks (tags, SLA, communications)
  assume agent permissions; Phase 12 replaces this bridge
  with the HD Customer role and record sync.

## 4. Tests (148 pass on beaverbill.localhost)

- New `test_portal_apis.py`: 20 pass. Guest and customer-less
  denial, session status, cross-customer denial on services,
  invoices, domains, backups, restores, tickets, and power;
  rate-limit trip; audit trail content; profile/contact CRUD;
  catalog/coupon (valid, unknown); cart/checkout/duplicates;
  coupon redemption counted once; invoice PDF/payment intent
  idempotency; power cycle; console single-use; reset/reinstall
  confirmations and idempotency; plan change with proration;
  DNS add/remove; certificate ordering; backup/restore flow;
  addon order/cancel; usage snapshots; ticket lifecycle with
  bad-attachment refusal; notification read/unread counts.
- Regression: all 128 pre-existing tests still pass,
  including the Phase 1 permission and Phase 3 ownership suites.
- Commands: `bench --site beaverbill.localhost migrate`,
  per-module `run-tests`, `python3
  scripts/beaverbill_phase_check.py phase-10`.

## 5. Gaps recorded honestly

- Browser and end-to-end HTTP evidence: not captured (no browser
  binary; APIs exercised in-process as session users).
- No live gateway/registrar/CA traffic; Test Gateway and
  simulated drivers back the flows.
- Evidence: `docs/phase-10-portal.md`,
  `docs/evidence/phase-10-baseline.json`.
