# Phase 0 — Baseline and ERPNext Prohibition Audit

Date: 2026-09-28. App: `beaverbill`. Site target: `beaverbill.localhost:8000`.

## 1. Stack baseline

| Component | Version / commit |
|---|---|
| Frappe Framework | 16.33.1 (`apps/frappe` @ `988e54f3c4c291e2077a83809663f123731abe76`) |
| BeaverBill app | `apps/beaverbill` @ `fea9159fa60aab2dd93927bd6e63769bb0cdd0de` |
| frappe/payments | `apps/payments` @ `86fefa9faf8ad825fe6f08c4753acfe44817900b` |
| frappe/helpdesk | `apps/helpdesk` @ `1c3361cc0019deec6f84035a9352270b4e4eb5cb` |
| frappe-ui (frontend dep) | `^1.0.0-rc.2` per `frontend/package.json`; vue `^3.5.22`, vite `^7.1.12`, tailwind `^3.4.18` |
| Python | 3.14.7 (bench venv); system 3.14.4 |
| Node / npm | v24.21.0 / 11.19.0 |
| Database client | MariaDB 11.8.6 client |
| Redis | server v=8.0.5 |
| OS | Ubuntu 26.04.1 LTS |
| Browser | none installed in this environment (no chrome/chromium binary) |

`required_apps` in `beaverbill/hooks.py` is `["frappe"]` only.

## 2. ERPNext prohibition confirmation

- `scripts/beaverbill_phase_check.py` `erpnext_scan` passes: no `import erpnext`,
  `from erpnext`, `"erpnext"` dependency, or `required_apps` ERPNext entry in
  `.py/.js/.ts/.vue/.json/.txt/.toml/.cfg` files.
- Manual grep for `erpnext` under `beaverbill/` returns only documentation
  mentions of the prohibition (plan/docs), no code dependency.
- Note: this bench also has `apps/erpnext` installed for other work, but
  BeaverBill does not require it and installs with Frappe only.

## 3. Existing DocTypes (16)

| DocType | Fields | Roles with access |
|---|---|---|
| Customer Credit Transaction | 5 | System Manager |
| Datacenter Asset | 5 | Hosting Admin, Hosting Support |
| Hosting Configurable Option | 4 | System Manager |
| Hosting Invoice | 7 | System Manager |
| Hosting Order | 7 | System Manager |
| Hosting Order Item | 4 | (none declared) |
| Hosting Product | 6 | System Manager |
| Hosting Product Addon | 3 | System Manager |
| Hosting Product Group | 2 | System Manager |
| Hosting Promo Code | 8 | System Manager |
| Hosting Provider Account | 5 | Hosting Admin, Hosting Support |
| Hosting Service Modification Request | 6 | System Manager |
| Hosting Subscription | 8 | System Manager |
| IPAM IP Address | 5 | Hosting Admin, Hosting Support |
| IPAM Subnet | 4 | Hosting Admin, Hosting Support |
| Server Node | 5 | Hosting Admin, Hosting Support |

## 4. Hooks, queues, scheduled jobs

- `after_install`: `beaverbill.setup.after_install`.
- `website_route_rules`: `/beaverbill/<path:app_path>` to `beaverbill`.
- `use_json_request_body = True`; `export_python_type_annotations = True`;
  `require_type_annotated_api_methods = True`.
- No active `scheduler_events`, `doc_events`, `permission_query_conditions`,
  or background-queue hooks (all commented out in `hooks.py`).
- No custom Redis/RQ queues declared by the app.

## 5. APIs

- One whitelisted method: `beaverbill/.../hosting_product.py:23`
  (`@frappe.whitelist()`).
- Portal route: `beaverbill/www/beaverbill.py` serves the SPA shell.
- No ERPNext routes or DocTypes referenced.

## 6. Provider drivers (`beaverbill/beaverbill/provisioning_drivers.py`)

`BaseProvisioningDriver`, `CPanelWHMDriver`, `DirectAdminDriver`,
`HetznerCloudDriver`, `OVHCloudDriver`, `ProxmoxVEDriver`,
`DedicatedServerIPAMDriver`, plus `get_provisioning_driver()` factory.

## 7. Test suite

- 15 `test_*.py` files under `beaverbill/`, 16 tests collected.
- Collection command (frappe must be importable, so the bench venv is used):
  `../env/bin/python -m pytest --collect-only -q beaverbill`
  from `apps/beaverbill`. `scripts/beaverbill_phase_check.py` now tries
  `sys.executable`, then the bench venv, then `/usr/bin/python3`.
- Full Frappe integration runs (`bench run-tests`) require a live site and are
  out of scope for the collection gate.

## 8. Baseline gaps recorded honestly

- Browser screenshots: not captured; no browser binary exists here.
  Evidence dir `docs/evidence/` is created for future portal/desk captures.
- Database/file backup restore drill: not executed in this pass; site
  `beaverbill.localhost` exists and `bench --site beaverbill.localhost backup`
  is the recorded drill command for a follow-up pass.
- These are informational only: the Phase 0 gate enforces progress scripts,
  ERPNext scan, git commit, audit doc, and test collection.

## 9. Test commands and evidence paths

- `python3 scripts/beaverbill_phase_check.py phase-0`
- `bash scripts/run_phase_gate.sh phase-0 --evidence docs/phase-0-audit.md --evidence docs/evidence/phase-0-baseline.json`
- Evidence: `docs/phase-0-audit.md`, `docs/evidence/phase-0-baseline.json`.
- Git hooks: `core.hooksPath` is `.githooks`; `.githooks/pre-commit` blocks
  hand edits to the generated `process.md` blocks.
