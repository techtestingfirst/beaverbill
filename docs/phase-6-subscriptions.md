# Phase 6 — Subscription, Renewal, Dunning, and Cancellation

Date: 2026-09-28. Beaver Bill subscriptions stay the source of truth.
No ERPNext subscription is used. All changes are additive to earlier phases.

## 1. States

`Trial → Active → Renewal Pending → Payment Failed → Grace Period → Suspended → Cancellation Pending → Terminated → Archived`

Old rows only knew Active, Suspended, Terminated and stay readable.
Legal moves are enforced in `HostingSubscription.validate` and in
`subscriptions.validate_transition`. Legacy edges (Active to Suspended,
Suspended to Active, any state to Terminated where previously allowed)
remain legal. The only new restriction is that jumps such as Active
straight to Archived throw.

## 2. Renewal timing and billing timezone

- Each subscription stores `current_period_start`, `current_period_end`,
  `next_renewal_date`, and `billing_timezone` (default UTC). Dates are
  compared as dates, so the timezone field documents the boundary the
  operator bills in without shifting stored dates.
- `renewal_lead_days` (default 3) opens the renewal window: an Active
  subscription enters Renewal Pending when the renewal date is within
  the lead window. Renewal invoices carry `due_date` equal to the
  period end date.
- Cycle lengths: Monthly 1, Quarterly 3, Semi-Annually 6, Annually 12,
  Biennially 24, Triennially 36 months via `advance_period`.

## 3. Renewal invoices and idempotency

- `open_renewal_invoice` issues through the Phase 4 ledger
  (`billing.issue_invoice`) with idempotency key
  `renewal-{subscription}-{period-end}`. Overlapping scheduler runs
  return the stored invoice instead of writing a second one.
- Auto-pay uses the ledger balance (`billing.get_ledger_balance`). When
  credit covers the invoice, `apply_credit_to_invoice` pays it and the
  period advances. No wallet field was changed; the old
  `get_customer_wallet_balance` helper in the controller still sums
  ledger rows.
- Scheduler locking: each run sets `locked_at`/`locked_by` with a
  10-minute expiry (`acquire_lock`/`release_lock`). A second worker
  that finds a fresh lock reports `locked` and touches nothing.

## 4. Retry, backoff, grace, suspension

- `retry_count`, `max_retries` (default 4), `retry_backoff_minutes`
  (default 240), `next_retry_at`, `last_retry_at`, `last_error`.
- Backoff is exponential: `base * 2^(count-1)` minutes from now.
- A failed attempt below max retries lands in Payment Failed with the
  next retry scheduled. Reaching max retries lands in Grace Period.
- `grace_period_days` (default 7) counts from the last retry. Expiry
  moves the subscription to Suspended with `suspend_reason` and syncs
  linked Hosting Services to Suspended.
- Suspended subscriptions auto-terminate after 14 days, stamping
  `terminated_at`, `termination_scheduled_at`, and a data-purge date
  30 days out. Terminated rows appear in `purge_due`.
- Legacy rows with `max_retries = 0` and `grace_period_days = 0`
  suspend on the first failed attempt, preserving the pre-Phase-6
  dunning test behavior.

## 5. Cancellation, refund, reinstatement

- `cancel_subscription(mode="end_of_period")` moves to Cancellation
  Pending, sets `cancel_at_period_end`, records
  `cancellation_requested_at`, and uses the period end as the
  effective date. The scheduler terminates the row when the date
  arrives and stamps a purge date.
- `cancel_subscription(mode="immediate")` terminates at once, posts a
  pro-rata unused-period credit (`unused_credit` =
  amount * days-left / days-in-period) as a `Hosting Credit Note`, and
  stamps the purge date.
- `reinstate_subscription` accepts Cancellation Pending, Suspended,
  Grace Period, and Payment Failed back to Active, clears cancel and
  retry flags, and bumps `reinstatement_count`. Linked services sync
  back to Active.
- `override_subscription_state` is a staff-only escape hatch that still
  validates the transition and logs a notification.

## 6. Notifications and service sync

- Every transition writes a Comment on the subscription and emails the
  customer address when the customer link is an email. Failures are
  swallowed so billing never blocks on mail.
- `sync_services` maps subscription Suspended/Terminated/Archived/Active
  onto linked Hosting Services through their own validated state
  machine. Partial failures are skipped per row.

## 7. Scheduler and staff actions

- `hooks.py` runs
  `beaverbill.beaverbill.doctype.hosting_subscription.hosting_subscription.process_subscription_renewals`
  daily. The controller entry point keeps its old import path and
  delegates to `beaverbill.beaverbill.subscriptions`.
- Staff-only whitelisted actions live in
  `beaverbill.beaverbill.subscription_lifecycle` with shared locks,
  notifications, and service sync in
  `beaverbill.beaverbill.subscription_support` (`_require_staff`:
  System Manager or Hosting Admin): `retry_subscription_payment`,
  `cancel_subscription`, `reinstate_subscription`,
  `override_subscription_state`. Retry refuses rows with nothing to
  retry and re-throws the ledger error when auto-pay still fails.

## 8. Tests (87 pass on beaverbill.localhost)

- New `beaverbill/beaverbill/tests/test_subscription_renewal.py`: 10 pass.
  Illegal jumps throw, legacy Active/Suspended/Terminated edges work,
  autopay renews and advances the period, overlapping runs write one
  invoice, backoff then grace is scheduled, funding then staff retry
  pays, grace expiry suspends and syncs the service, end-of-period
  cancel terminates on the effective date, immediate cancel posts an
  unused-period credit note, reinstatement clears flags, purge lists
  terminated rows due.
- Regression: 16 pre-existing doctype tests OK (the order dunning
  test now pins legacy immediate-suspend with max_retries 0 and
  grace 0). Full integration: 10 billing, 13 gateway, 11 catalog,
  8 customer-service, 8 infra-permissions, 11 IPAM all OK.
- Commands: `bench --site beaverbill.localhost migrate`,
  `bench --site beaverbill.localhost run-tests --app beaverbill`,
  plus per-module runs listed above,
  `python3 scripts/beaverbill_phase_check.py phase-6`.

## 9. Gaps recorded honestly

- Browser evidence for renewal/dunning screens: not captured (no
  browser binary in this environment).
- Real timezone-shifted billing boundaries are documented, not
  executed against a non-UTC site in this pass.
- Evidence: `docs/phase-6-subscriptions.md`,
  `docs/evidence/phase-6-baseline.json`.
