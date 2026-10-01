# AGENTS.md — BeaverBill

Self-contained Frappe hosting-billing app. No ERPNext — never add imports, DocTypes (`Customer`, `Sales Invoice`, `Payment Entry`), or dependencies. Full setup + customer test path: `SETUPGUIDE.md`. End-user manual: `docs/user-manual.md`. Architecture: `docs/architecture.md`. Customer/staff runbooks: `docs/guides.md`.

## Invariants (do not break)

- Additive only: never rename/delete DocTypes, fields, hooks, roles, APIs, fixtures, status values without migration plan. Preserve API signatures; wrap changes in compat shims.
- Never hand-edit phase status. Gate only: `bash scripts/run_phase_gate.sh <phase-id>`. Status source: `progress/phase-status.json`.
- State machines enforced server-side (`docs/architecture.md` §3); illegal jump = `ValidationError`. Money corrections = new docs only, never in-place edits.
- Every portal call passes `portal/guard.py` (rate limit → ownership → audit); row ownership via `permissions.py` (`permission_query_conditions` + `has_permission` in `hooks.py`). Cross-customer access must deny.

## Layout (real entrypoints)

- `beaverbill/beaverbill/portal/` — whitelisted SPA APIs (`account,billing,catalog,orders,services,assets,support,public`); `www/beaverbill.py` + `frontend/src/router.ts` (base `/beaverbill`, `website_route_rules` in `hooks.py`).
- Engines: `billing.py, gateways.py+webhooks.py, subscriptions*.py, modifications*.py, provisioning*.py, domains.py, certificates.py, backups.py, addons.py, helpdesk_sync.py, monitoring.py, reconciliation.py, security*.py, deployment.py`.
- 56 DocTypes in `beaverbill/beaverbill/doctype/`; scheduler jobs (daily, lock-guarded) in `hooks.py:scheduler_events`.
- Stack that matters: `required_apps=["frappe"]`; CI installs `telephony,payments,helpdesk` alongside (`.github/workflows/ci.yml`); local site `beaverbill.localhost`.

## Commands (bench runs from `~/frappe/frappe-bench`)

```bash
bench --site beaverbill.localhost migrate
bench --site beaverbill.localhost run-tests --app beaverbill   # 195 + 16 stubs, ~135s
bench --site beaverbill.localhost execute beaverbill.beaverbill.deployment.release_status  # smoke
cd apps/beaverbill/frontend && npm run build && npm run type-check
bash apps/beaverbill/scripts/deploy_beaverbill.sh <site> [--branch <ref>]
```

- Pre-commit: ruff + eslint + prettier (`pre-commit run --all-files`); ruff rules in `pyproject.toml`.
- `use_json_request_body=True`: send non-GET portal bodies as native JSON. `export_python_type_annotations` + `require_type_annotated_api_methods`: all whitelisted methods need annotations.
- Destructive portal actions need confirmation flag + idempotency key (retry same key returns original). Console tickets 15-min single-use. Store gateway `token_reference` only, never card numbers.

## Gotchas

- IPAM: subnets auto-create host rows on insert; never hand-insert addresses.
- Provider endpoints: public http(s) 80/443 only (SSRF guard rejects private/metadata hosts); console needs driver with `get_vnc_console`.
- Unknown destructive provisioning outcome → `Manual Review`, never blind-retry terminate.
- Backup key ships beside ciphertext locally; production must vault it. Live `bench restore` needs MariaDB root — staging-first.
- Browser e2e/a11y/load tests never ran here (no browser binary); portal coverage is API-layer + `npm build/type-check`.


## Sites
- my backend site is beaverbill.localhost:8000
- my frontend site is beaverbill.localhost:8080
- Admin user is Administrator/admin
- client user is thestockdot@gmail.com/HR&THAT0

## Referance
- Before making any change or writing code check the codes of erpnext how perticular thing is handeled and written in erpnext and than follow the same style.