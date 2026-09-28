# Phase 8 — Provisioning Orchestration and Driver Reliability

Date: 2026-09-28. All changes are additive. Existing driver
signatures, simulated provisioning hooks, subscription and
modification flows keep working unchanged.

## 1. Preserved behavior

- Every method on `BaseProvisioningDriver` and all six concrete
  drivers keeps its exact legacy signature and return shape.
  `get_provisioning_driver` resolves the same six types and still
  raises `ValueError` for unknown types.
- `modifications.resize_service_resources` still calls the driver
  directly with a simulated fallback for Custom/missing providers.
- Hosting Service states, subscription sync, and the Phase 7
  modification engine are untouched.

## 2. Versioned driver contract (`provisioning_drivers.py`)

- `DRIVER_CONTRACT_VERSION = "2.0"` on the base class;
  `capabilities()` advertises supported verbs (additive; existing
  drivers inherit it without edits).
- `ProvisioningError` carries `error_type` (transient,
  rate_limited, capacity, permanent, unknown), a default retryable
  flag per type, and an optional provider code.
- `classify_exception` maps arbitrary driver exceptions to an
  error type (rate-limit, capacity, timeout/connection, not-found
  heuristics; unclassifiable becomes unknown, never retried blind).
- `call_driver_action` wraps every verb with timing, legacy-result
  normalization, and exception wrapping; `NotImplementedError`
  (e.g. a driver without `describe`) becomes non-retryable unknown.
- `describe(subscription_name)` is new on the base and raises
  `NotImplementedError` by default; reconciliation records Unknown
  instead of failing. No existing driver was forced to implement it.
- `safe_summary` redacts anything resembling a secret before it
  reaches logs; `request_hash` gives stable non-secret call hashes.

## 3. Records (all new, no schema touched on old DocTypes)

- `Provisioning Operation`: service, subscription, customer,
  operation_type (Create/Resize/Suspend/Unsuspend/Terminate/Reboot/
  Console), status (Pending/Queued/Running/Succeeded/Failed/
  Retrying/Manual Review/Compensated/Cancelled), unique
  `idempotency_key`, `correlation_id`, provider account, driver
  type, timeout, max retries, retry count, next retry, error type,
  last error, secrets-free provider metadata, timestamps. Server-side
  transition guard; Queued pre-flight failures may move directly to
  Retrying/Failed/Manual Review.
- `Provisioning Attempt`: per-try audit (number, status, timing,
  duration, request/response summaries, error). Unique per
  (operation, attempt_no).
- `Provider Request Log`: append-only (hash immutable), with
  correlation ID, action, request hash, safe summaries, error type,
  latency.
- `Reconciliation Result`: service, local/remote state, verdict
  (Matched/Mismatched/Orphaned Local/Orphaned Remote/Unknown),
  details, timestamp.
- `Resource Cleanup Task`: compensation work items (Release IP,
  Remove DNS, Revoke Console, Purge Data, Restore Snapshot, Manual
  Check) with Pending/Done/Failed/Skipped guard.

## 4. Engine (`provisioning.py`)

- `queue_operation` is idempotent by key and inherits service
  links (subscription, customer, provider account) from the service.
- `run_operation` locks the row, honors retry-due timestamps,
  treats stale Running runs as unknown outcomes, capacity-checks
  the target Server Node (maintenance/offline blocks with
  error_type capacity), resolves the driver by provider account
  (Custom/missing stays simulated and logged), records an Attempt
  plus a Request Log on every path, and syncs the service on
  success (Pending walks through Provisioning to keep the state
  machine valid; upstream metadata stores correlation ID and the
  safe result).
- Retry rules by error type: transient/rate_limited/capacity back
  off 5/15/60 minutes with exponential growth capped at 24h;
  permanent never retries; **destructive actions with unknown
  outcome never auto-retry** and go to Manual Review.
- Partial-failure compensation: Failed operations spawn cleanup
  tasks (type depends on operation); `compensate_operation` (staff)
  adds manual-compensation tasks and marks Compensated.
- Staff actions (whitelisted, annotated, permission-checked):
  `retry_operation`, `cancel_operation`, `compensate_operation`,
  `reconcile_now`.
- Reconciliation: `reconcile_service` uses injected remote state or
  driver `describe`, normalizes aliases (running/on, off, deleted/
  destroyed/absent), and detects orphans both ways
  (Terminated-locally-but-present-remotely and vice versa).
  `orphaned_resources` lists latest non-clean verdicts.
  Service stamping uses `db.set_value` to avoid clobbering
  concurrent edits.
- Scheduler: `process_queued_operations` runs from the daily
  scheduler hook (appended, existing entries kept) and commits per
  operation.

## 5. Tests (100 pass on beaverbill.localhost)

- New `test_provisioning_orchestration.py`: 18 pass. Contract
  version, legacy signatures on all six drivers, exception
  classification table, result normalization, error wrapping,
  backoff growth, retry rules incl. destructive-unknown refusal,
  idempotent queue, create-success activation with attempt plus
  request log, transient retry-then-success, permanent no-retry
  with cleanup tasks, destructive-unknown to Manual Review,
  compensation, capacity block, reconcile matched/mismatched/
  unknown, orphaned-remote detection plus listing.
- Regression: 10 billing, 11 catalog, 8 customer-service,
  13 gateway, 8 infra, 11 IPAM, 11 modifications, 10 subscription,
  plus 16 pre-existing doctype tests, all OK.
- Commands: `bench --site beaverbill.localhost migrate`,
  per-module `run-tests`, `python3
  scripts/beaverbill_phase_check.py phase-8`.

## 6. Gaps recorded honestly

- Browser evidence for operation screens: not captured (no browser
  binary in this environment).
- No live provider traffic; drivers are exercised through
  fault-injection fakes plus the simulated path. Sandbox tests
  against real provider APIs remain future work (Phase 14).
- Evidence: `docs/phase-8-provisioning.md`,
  `docs/evidence/phase-8-baseline.json`.
