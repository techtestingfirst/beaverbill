# Phase 16 — Deployment, Backup, Disaster Recovery, and Release

Date: 2026-09-28. Additive only: `deployment.py` checks, two scripts,
one test suite, version manifests, and a real backup drill. No app
behavior changed.

## 1. Automated deployment

`scripts/deploy_beaverbill.sh <site> [--branch <ref>]` performs the
full path: fetch checkout, skip-if-installed `install-app`, `migrate`,
frontend build, service restart, `enable-scheduler`, `doctor`, and a
version snapshot. Safe-deploy order for staging and production:

1. Snapshot versions (`beaverbill_snapshot_versions.py`) and take a
   pre-deploy backup (section 5).
2. Enable maintenance mode on the site.
3. Deploy to staging first; run migrations there and the full suite.
4. Deploy to production; `migrate`; restart; disable maintenance.
5. Run post-release smoke (`deployment.release_status`, section 4).
6. Keep the previous commit checked out in a standby worktree until
   smoke passes (rollback, section 7).

## 2. Version manifest

`docs/evidence/phase-16-versions.json` (written by
`scripts/beaverbill_snapshot_versions.py --root <bench> --site
<site>`): bench path, Python 3.14.7, Node v24.21.0, MariaDB client
11.8.6, Redis 8.0.5, and every app installed on the release site
with full commit SHA (frappe `988e54f`, beaverbill at release
commit, payments `86fefa9`, helpdesk `1c3361c`, telephony
`039cf39`), plus the beaverbill `0.0.1` version. Only site
installed apps are recorded, so the manifest itself stays free of
non-site dependencies.

## 3. Workers and scheduler

`deployment.validate_scheduler` asserts the scheduler is enabled,
all eight lifecycle jobs are registered (renewals, provisioning,
domains, certificates, backups, helpdesk sync, monitoring,
reconciliation), and the cache/queue layer answers. `bench doctor`
is part of the deploy script. Release blockers
(`deployment.check_release_blockers`) fail the release when
`ignore_csrf`, `allow_tests`, or `maintenance_mode` is set.

## 4. Post-release smoke

`deployment.run_smoke_tests` (read-only): database `select 1`,
core DocType reads, a live pricing quote, and a full monitoring
cycle. `release_status` bundles versions, scheduler, smoke, and
the no-ERPNext proof for staff.

## 5. Backup drill (executed 2026-09-29 on beaverbill.localhost)

- `bench backup --with-files --compress`: 1.7 MB database dump
  (348 tables, gzip integrity ok), public/private file tars (both
  list ok), site-config backup. SHA-256 manifest recorded.
- Database copy encrypted with AES-256-CBC (salt, PBKDF2); key at
  `sites/.../private/backups/backup.key` (0600). Decrypt round-trip
  verified byte-identical.
- Retention: 30 days of daily backups in
  `sites/.../private/backups/` (see `enforce_retention` for
  service-level data). Evidence:
  `docs/evidence/phase-16-backup.json`.

## 6. Restore procedure and recovery objectives

- RPO: 24 h (daily backups). RTO: 2 h for full site rebuild,
  30 min for database-only restore with files intact.
- Restore: decrypt the database copy, then
  `bench --site <site> restore <db.sql.gz> --with-public-files
  <files.tgz> --with-private-files <private.tgz>`, followed by
  `migrate`, `release_status` smoke, and canary count comparison.
- Queues/jobs restore: scheduler state rebuilds from DocTypes on
  `migrate`; re-run `enable-scheduler` and confirm
  `validate_scheduler`. Credentials restore: `Password` fields
  decrypt with the site `encryption_key` from the site-config
  backup — that file is part of every backup set.
- Status: backup, encryption, and integrity verified live; the
  destructive same-site restore was **not executed** because
  `bench restore` requires the MariaDB root password, which is
  unavailable in this environment (the refused restore left the
  site byte-identical, verified by canary counts). First staging
  provisioning must execute the restore before production data
  exists.

## 7. Rollback

- Code: `git checkout <previous-sha>` in `apps/beaverbill`,
  `bench --site <site> migrate`, restart, smoke. DocType removals
  are never part of a release (additive policy), so downgrade
  migrations are schema-safe.
- Data: restore the pre-deploy backup set (section 6). Invoices,
  payments, and ledger rows are never rewritten by deploy code,
  only appended by business flows.
- ERPNext-free confirmation: installed apps on the release site
  are `frappe, beaverbill, payments, telephony, helpdesk`;
  `required_apps == ["frappe"]`; the ERPNext import scan passes.

## 8. Tests (`test_deployment_release.py`, 7 cases)

Scheduler validation, smoke pass, versions manifest shape,
deploy-script steps present and executable, no-ERPNext proof,
dev-blocker detection, and backup evidence integrity (hashes,
encryption round-trip, restore status recorded with reason).

## 9. Gaps recorded honestly

- Live restore untested (no DB root); staging must run it first.
- Backup key lives beside the ciphertext; production must move it
  to a vault with rotation (documented, not implemented here).
- Evidence: `docs/phase-16-release.md`,
  `docs/evidence/phase-16-backup.json`,
  `docs/evidence/phase-16-versions.json`,
  `docs/evidence/phase-16-baseline.json`.
