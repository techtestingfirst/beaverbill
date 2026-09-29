# Setup Guide — BeaverBill

Local dev site: `beaverbill.localhost:8000` (bench at `~/frappe/frappe-bench`, apps installed: `frappe, beaverbill, payments, telephony, helpdesk`).

## 1. First-time setup

```bash
cd ~/frappe/frappe-bench
bench get-app beaverbill <repo-url> --branch developer   # skip if apps/beaverbill exists
bench new-site beaverbill.localhost --admin-password admin
bench --site beaverbill.localhost install-app beaverbill
bench --site beaverbill.localhost migrate
bench build --app beaverbill
bench --site beaverbill.localhost enable-scheduler
bench start   # serves :8000; Desk at /app, portal at /beaverbill
```

Frontend dev (optional, proxy to bench):

```bash
cd apps/beaverbill && npm run dev      # root postinstall/dev wraps frontend/
cd apps/beaverbill/frontend && npm run build && npm run type-check  # verify SPA
```

Pre-commit (formatting/lint gate):

```bash
cd apps/beaverbill && pre-commit install && pre-commit run --all-files
# ruff (py) + eslint + prettier (js/vue); ruff config in pyproject.toml
```

Deploy / staging (idempotent):

```bash
bash apps/beaverbill/scripts/deploy_beaverbill.sh <site> [--branch <ref>]
# does: install-app (skip-if-done) -> migrate -> bench build -> restart -> enable-scheduler -> doctor -> version snapshot
bench --site <site> execute beaverbill.beaverbill.deployment.release_status  # post-deploy smoke
```

## 2. Backend verification

```bash
bench --site beaverbill.localhost migrate
bench --site beaverbill.localhost run-tests --app beaverbill            # full suite: 195 + 16 DocType stubs (~135s)
bench --site beaverbill.localhost run-tests --app beaverbill --module "beaverbill.beaverbill.tests.test_release_journeys"  # single module
bench --site beaverbill.localhost run-tests --app beaverbill --test "test_checkout_creates_order"  # single test (-k style filter via --test)
python3 apps/beaverbill/scripts/beaverbill_phase_check.py <phase-id> --root apps/beaverbill
bash apps/beaverbill/scripts/run_phase_gate.sh <phase-id>   # only way to mark phases complete; never edit progress/phase-status.json by hand
```

Backup drill:

```bash
bench --site beaverbill.localhost backup --with-files --compress
# restore: bench --site <site> restore <db.sql.gz> --with-public-files <pub.tgz> --with-private-files <priv.tgz> && bench --site <site> migrate
# needs MariaDB root pw; live restore untested locally — run on staging first (see docs/phase-16-release.md)
```

## 3. Test as a customer (portal workflow)

Portal SPA: `http://beaverbill.localhost:8000/beaverbill` (serves `frontend/`, route `/beaverbill/<path>`, history base `/beaverbill`).
All portal APIs are session-authenticated (`/api/method/beaverbill.beaverbill.portal.*`); guests reach only `signup`, `verify_email`, `resend_verification`, webhook URL.

End-to-end customer path (routes + API, mirrors `test_release_journeys`):

1. **Sign up / verify**: `/signup` → `portal.public.signup(full_name, email, password)` → 24h token email → `/verify` (`verify_email`; `resend_verification` if expired). Login at `/login`.
2. **Browse / configure**: `/catalog`, `/catalog/:name` → `list_products`, `get_product`; configure options/addons; `validate_coupon` for valid + invalid codes.
3. **Cart / checkout**: `/cart` (`cart_add/remove/clear`), `/checkout` → `get_cart`, `cart_coupon`, `checkout` with own idempotency key (retry same key → `duplicate_request`, no double order). Result: `Hosting Order` snapshot (Draft → Confirmed → Payment Pending).
4. **Pay**: `/invoices`, `/invoices/:name` → `list_invoices`, `get_invoice`, `invoice_pdf`; `pay_invoice` (gateway + saved method or new **token reference** — never card numbers), `payment_status`, `list_gateways`, `list/add/remove_payment_methods`. Webhook (HMAC, idempotent, handles duplicates/out-of-order) → allocation → invoice Paid. Failure path: `payment_status` Failed → retry; staff `retry_failed_payment` / `replay_payment_event`.
5. **Use services**: `/` (dashboard), `/services`, `/services/:name` → `service_dashboard/detail/usage`; `power` (reboot/poweroff/poweron → queued tracked operation); console button → `console_url` (15-min single-use ticket) → `console_ticket`; `password_reset`, `os_reinstall` (both need confirmation + idempotency key; reinstall also data-loss ack); `change_plan` (upgrade/downgrade → proration + approval).
6. **Domains / SSL / backups / addons**: `/domains` (`my_domains`, `domain_detail`, `dns_add/remove`, `my_certificates`, `request_certificate`), `/backups` (`my_backups`, `request_restore` → staff approval → `restore_status`, `storage_usage`), `/addons` (`my_addons`, `order_addon`, `cancel_addon`).
7. **Support / profile**: `/tickets`, `/tickets/:name` (`create_ticket`, `ticket_list/detail/reply`; internal agent notes hidden), `/profile` (`get_profile`, `update_profile`, `list/add/update/delete_contact`, `session_status`).

Quick smoke without browser: sign up via Desk/bench console or `curl` signup → login → call `list_products`, `get_cart`, `checkout`, `pay_invoice`, `service_dashboard` in order; expect state chain Order Paid → service Provisioning → Active; invoice Draft → Issued → Paid.

## 4. App workflow (money → service → lifecycle)

```
Catalog price → cart quote → order snapshot → invoice snapshot
  → gateway intent → signed webhook → allocation → invoice Paid
  → provisioning op (Pending→Queued→Running→Succeeded) → service Active
  → subscription renewals/dunning (scheduler, lock-guarded, idempotent)
```

- State machines (server-enforced, illegal jump = ValidationError): Order `Draft→Confirmed→Payment Pending→Paid→Processing→Completed→Cancelled`; Invoice `Draft→Issued→Partially Paid→Paid→Overdue→Cancelled→Written Off`; Payment `Created→Authorized→Captured→Failed→Refunded→Partially Refunded→Chargeback`; Subscription `Trial→Active→Renewal Pending→Payment Failed→Grace Period→Suspended→Cancellation Pending→Terminated→Archived`; Service `Pending→Provisioning→Active→Modification Pending→Suspended→Cancellation Pending→Terminated→Archived`; Provisioning op `Pending→Queued→Running→Succeeded→Failed→Retrying→Manual Review→Compensated`.
- Money: corrections are new docs (refunds, credit/debit notes, wallet ledger via `Customer Credit Transaction`), never in-place edits; over/under-payments surface in `credit_ledger_mismatch` / `invoice_outstanding` reports.
- Provisioning: idempotent ops + capacity check + versioned driver contract (v2.0, legacy adapters); unknown destructive outcome parks in `Manual Review` — never blind-retry terminate.
- Scheduler (daily, all lock-guarded): renewals, due modifications, queued ops, domain renewals, cert monitor, addon renewals, backups, retention, storage overage, helpdesk sync, monitoring, reconciliation.
- Helpdesk: same-site `helpdesk` app; BeaverBill `Hosting Customer`/contacts canonical, HD rows mirrors via `helpdesk_sync`.
- Troubleshooting: see `docs/guides.md` §5 + runbooks §6; deep dives in `docs/architecture.md`, `docs/phase-10-portal.md`, `docs/phase-11-portal-ui.md`, `docs/phase-14-testing.md`, `docs/phase-16-release.md`.
