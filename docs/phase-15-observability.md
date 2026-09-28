# Phase 15 — Observability and Reconciliation

Date: 2026-09-28. All changes are additive: a `Monitoring Alert`
record, `monitoring.py`, `reconciliation.py`, two scheduler entries,
permission hooks, and one test suite. No existing behavior changed.

## 1. Monitoring (`monitoring.py`)

Thirteen read-only checks run on the scheduler (`daily`) through
`run_monitoring_cycle`, and on demand through the staff-only
`health_dashboard` API:

| Check | Warn | Fail |
|---|---|---|
| `mon:failed_payments` (24 h) | ≥ 1 | ≥ 5 |
| `mon:unprocessed_webhooks` (stale > 15 min) | pending | any failed, or > 10 pending |
| `mon:renewal_failures` (Payment Failed/Grace) | ≥ 1 | ≥ 10 |
| `mon:provisioning` (failed 24 h; Queued/Running > 2 h) | ≥ 1 failed | ≥ 5 failed, or any stuck |
| `mon:provider_errors` (24 h) | ≥ 1 | ≥ 20 |
| `mon:ip_exhaustion` (per subnet) | < 10 % free | 0 free |
| `mon:expiring_domains` (Active) | ≤ 30 d | ≤ 7 d |
| `mon:expiring_certificates` | ≤ 30 d | ≤ 7 d |
| `mon:backup_failures` (24 h) | ≥ 1 | ≥ 5 |
| `mon:email_failures` (Email Queue, 24 h) | ≥ 1 | ≥ 10 |
| `mon:helpdesk_sync` (failed rows) | ≥ 1 | ≥ 10 |
| `mon:orphaned_cleanup` (stale Pending > 24 h) | ≥ 1 | any stale |
| `mon:ledger` (running-sum mismatches, overdue) | overdue | any mismatch |

`run_checks` never raises: a crashing check reports `fail` with the
error as detail, so one broken probe cannot blind the rest.

## 2. Alerting

One open `Monitoring Alert` per failing check (Warning/Critical,
first/last seen, auto `Resolved` on recovery). A newly failing
check mails System Managers best-effort; repeat cycles update the
same row instead of spamming. Alerts are staff-only in desk
(System Manager full, Hosting Admin triage, Hosting Support read).

## 3. Reconciliation (`reconciliation.py`)

Eight read-only pair runners, capped at 50 rows each, on the daily
scheduler through `run_reconciliation_cycle`:

- `gateway_vs_payments`: processed events pointing at missing
  payments; captured payments with an invoice but no allocation.
- `invoices_vs_payments`: Paid invoices with outstanding balance;
  invoices overdue more than 90 days.
- `ledger_vs_balances`: reuses `billing.ledger_mismatches`.
- `services_vs_providers`: live vs remote status through drivers
  that implement `describe`; others are counted as skipped, never
  as mismatches.
- `ipam_vs_assignments`: allocations pointing at deleted records
  or at terminated/archived services.
- `subscriptions_vs_invoices`: renewal invoices that went missing;
  terminated subscriptions with live services.
- `helpdesk_vs_customers`: HD customers without logins and Beaver
  Bill customers without HD mirrors (skipped when helpdesk is
  absent).
- `domains_vs_registrar`: locally Active domains missing from the
  simulated registry or with divergent expiry; external registrar
  accounts are counted as skipped (cannot be queried offline).

Mismatched pairs raise one Warning alert each (`recon:<pair>`);
clean pairs auto-resolve. Existing desk reports
(`gateway_reconciliation`, `unprocessed_webhooks`,
`invoice_outstanding`, `credit_ledger_mismatch`,
`ip_pool_exhaustion`, `duplicate_ip_allocation`) remain the
drill-down views behind these alerts.

## 4. Tests (`test_monitoring_reconciliation.py`, 9 cases)

Seeded faults per check (failed payment, stale webhook, stuck op,
urgent domain/cert, exhausted pool), seeded mismatches (paid-with-
balance invoice, tampered ledger row, dangling IPAM, vanished
registry entry), alert dedup across cycles, resolve-on-recovery,
and dashboard staff-only denial. Commands:

```bash
bench --site beaverbill.localhost migrate
bench --site beaverbill.localhost run-tests --app beaverbill \
  --test test_monitoring_reconciliation
python3 scripts/beaverbill_phase_check.py phase-15
```

## 5. Gaps recorded honestly

- Checks run daily; there is no paging or sub-hour alerting.
- Provider-side truth is limited to drivers with `describe`
  and the simulated registrar; external panels are skipped.
- Admin email delivery depends on site mail configuration.
- Evidence: `docs/phase-15-observability.md`,
  `docs/evidence/phase-15-baseline.json`.
