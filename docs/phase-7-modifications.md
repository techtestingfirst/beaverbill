# Phase 7 — Upgrade, Downgrade, and Modification Reliability

Date: 2026-09-28. All changes are additive to earlier phases. The
existing modification DocType, proration mathematics, invoice and
credit-note behavior, and simulated provisioning hooks keep working.

## 1. Preserved behavior

- `HostingServiceModificationRequest.calculate_proration`,
  `process_modification`, `apply_subscription_change`, and
  `trigger_provisioning_resize` keep their exact legacy semantics for
  direct callers. `validate` still prorates Pending requests, but only
  when the amount is empty so engine-frozen values are never clobbered.
- Legacy proration covers Monthly, Quarterly, Semi-Annually, Annually,
  and past-due inputs. The engine (`modifications.compute_proration`)
  returns identical values for all of them (asserted by compatibility
  tests). Biennially/Triennially previously fell back to one month;
  the engine uses 24/36 months. That correction is intentional and
  documented here; no legacy test covered those cycles.
- Without a linked service, resize stays a logged simulated hook.
- Downgrade credits in the legacy path still write the same
  `Customer Credit Transaction` shape.

## 2. Records

- `Hosting Service Modification Request` gains additive fields only:
  `service`, `effective_mode` (Immediate, default, or Next Cycle),
  `effective_date`, `idempotency_key` (unique), `old_product`,
  `old_amount`, `old_billing_cycle`, `old_product_snapshot`,
  `new_product_snapshot`, `usage_snapshot`, `downgrade_warnings`,
  `data_loss_acknowledged`, `failure_reason`, `applied_at`, and an
  `events` table. Status grows Pending, Approved, Applying,
  Completed, Failed, Compensated, Rejected. Old rows read unchanged.
- `Hosting Modification Event` (child table): timestamp, action,
  actor, detail. Every request logs Created, Snapshots Frozen,
  Proration Calculated, Approved, Apply Started, Resize
  Succeeded/Failed, Rolled Back, Compensated, Completed.
- `Hosting Product` gains optional specs `cpu_cores`, `ram_mb`,
  `disk_gb`, `bandwidth_gb` (0 = unspecified). Old products read as
  unspecified and skip spec checks.

## 3. Engine (`modifications.py`, `modification_apply.py`, `subscription_support.py`)

- `request_modification` is idempotent by key, locks the subscription
  row, enforces the policy gate (Trial, Active, or Renewal Pending;
  no pending cancellation), refuses a second open request per
  subscription (concurrency control), freezes both product snapshots
  plus service usage, and stores proration.
- `approve_modification` is a safe no-op on Approved rows. Immediate
  upgrades raise an invoice through the Phase 4 ledger with key
  `{request}-invoice`. Next Cycle approvals defer billing to apply time.
- `apply_modification` requires a Paid upgrade invoice, moves through
  Applying, resizes through the real provider driver resolved from
  the service's provider account (Custom or missing stays simulated),
  and completes with a ledger-backed downgrade credit for negative
  proration (key `{request}-credit`).
- Rollback: a resize failure restores product, amount, and cycle from
  the frozen snapshot, cancels the unpaid upgrade invoice, marks the
  request Failed with the reason, and re-syncs services.
  `compensate_modification` (staff only) posts a ledger credit note
  for collected money and marks Compensated. `retry_modification`
  re-runs Failed rows through Approved.
- `apply_due_modifications` runs daily from `hooks.py` and applies
  Next Cycle requests whose effective date (period end at request
  time) has arrived. The controller keeps a delegating entry point.

## 4. Downgrade safety

- `downgrade_warnings_for` lists shrinking specs. Shrinking without
  `data_loss_acknowledged` throws with the explicit warning text.
- `check_downgrade_usage` reads `usage` from the service's
  `upstream_metadata` JSON and blocks when recorded usage exceeds the
  new product cap, naming the offending dimension.

## 5. Cancellation and refund policy

- `check_policy` blocks modifications on Suspended, Grace Period,
  Payment Failed, Cancellation Pending, Terminated, and Archived
  subscriptions, and on rows with `cancel_at_period_end`. Downgrades
  credit the ledger; they never issue cash refunds. Upgrades require
  payment before apply.

## 6. Tests (98 pass on beaverbill.localhost)

- New `test_service_modifications.py`: 11 pass. Proration compat
  across four cycles plus due and past-due inputs, snapshot freezing,
  immediate upgrade invoice-then-apply, next-cycle deferral with
  payment gate and dated apply, usage-blocked downgrade, warning plus
  ack with ledger credit, idempotent request and approve with one
  invoice, concurrent request refused, failed resize with restore plus
  invoice handling plus compensation credit, policy blocks.
- Regression: 16 pre-existing doctype tests OK, plus 10 subscription,
  10 billing, 13 gateway, 11 catalog, 8 customer-service, 8 infra,
  11 IPAM integration tests OK.
- Commands: `bench --site beaverbill.localhost migrate`,
  `bench --site beaverbill.localhost run-tests --app beaverbill`,
  per-module runs, `python3 scripts/beaverbill_phase_check.py phase-7`.

## 7. Gaps recorded honestly

- Browser evidence for modification screens: not captured (no browser
  binary in this environment).
- Real provider resize was not executed; drivers are invoked by type
  with a simulated fallback, and failure paths are covered by an
  injected resize fault.
- Evidence: `docs/phase-7-modifications.md`,
  `docs/evidence/phase-7-baseline.json`.
