# Phase 14 — Testing and Visual Verification

Date: 2026-09-28. All changes are additive: two new journey suites,
one release-health suite, and shared fixtures. No DocType, API, or
workflow was changed.

## 1. Layers and where they run

- **Unit tests**: pricing math, proration, validators, driver
  classification (`test_catalog_pricing`, `test_service_modifications`,
  `test_security_compliance`, `test_release_health` perf smoke).
- **Frappe integration tests**: every DocType workflow on
  `beaverbill.localhost` (all 18 `test_*` modules).
- **Migration tests**: `bench migrate` clean;
  `test_release_health` asserts every `patches.txt` entry resolves
  to a file and every DocType JSON parses with permissions.
- **Driver contract tests**: `test_provisioning_orchestration`
  pins contract v2.0 and legacy signatures for all six drivers.
- **Provider sandbox tests**: simulated registrar, certificate,
  backup, addon, and gateway adapters with fault injection;
  no live provider traffic (documented gap).
- **Payment webhook tests**: signature, schema, idempotency,
  out-of-order walk, capture/refund/chargeback separation,
  replay (`test_gateway_webhooks` plus journey duplicates).
- **Helpdesk sync tests**: idempotent mirrors, retries, internal
  note hiding, cross-customer denial (`test_helpdesk_sync`).
- **API tests**: portal ownership, commerce, services, assets,
  tickets (`test_portal_apis`, `test_portal_billing_extras`,
  `test_portal_signup`, `test_security_compliance`).
- **Release journeys (new)**: `test_release_journeys` walks
  cart → checkout → signed webhooks → Paid invoice → provision →
  power/console → upgrade → renewal → dunning → reinstate →
  cancel → terminate; `test_release_journeys_assets` walks
  domain renew (invoice → credit → registrar) and SSL
  request → validate → install → renew, plus ticket creation
  with duplicate protection and cross-customer denial.
- **Security tests**: `test_security_compliance` (14 cases).
- **Frontend static verification**: `npm run build` and
  `npm run type-check` (vue-tsc) clean in `frontend/`.
- **Clean install without ERPNext**: `required_apps == ["frappe"]`,
  ERPNext import scan passes, full suite runs on a site where
  ERPNext is not installed.

## 2. Required journeys and covering suites

| Journey | Suite |
|---|---|
| Registration and verification | test_portal_signup |
| Catalog browsing and configuration | test_catalog_pricing, test_portal_apis |
| Valid and invalid coupons | test_catalog_pricing, test_release_journeys |
| Tax and currency calculation | test_catalog_pricing |
| Checkout and successful payment | test_release_journeys |
| Payment failure and retry | test_gateway_webhooks, test_release_journeys |
| Duplicate webhook delivery | test_gateway_webhooks, test_release_journeys |
| Successful provisioning | test_provisioning_orchestration, test_release_journeys |
| Provisioning failure and recovery | test_provisioning_orchestration |
| Service dashboard access | test_portal_apis |
| Power operation | test_portal_apis, test_release_journeys |
| Console access | test_portal_apis, test_release_journeys |
| Upgrade and proration | test_service_modifications, test_release_journeys |
| Downgrade and credit | test_service_modifications |
| Renewal | test_subscription_renewal, test_release_journeys |
| Dunning and suspension | test_subscription_renewal, test_release_journeys |
| Reinstatement | test_release_journeys |
| Cancellation and termination | test_release_journeys |
| Domain and SSL renewal | test_domains_ssl_backups, test_release_journeys_assets |
| Ticket creation and response | test_helpdesk_sync, test_release_journeys_assets |
| Unauthorized access attempts | test_portal_apis, test_security_compliance, test_release_journeys_assets |

## 3. Full suite results

`bench --site beaverbill.localhost run-tests --app beaverbill`:

- `Ran 195 tests — OK` (integration suites, ~135 s).
- `Ran 16 tests — OK` (DocType stub suites).
- New suites: `test_release_health` (7),
  `test_release_journeys` (5), `test_release_journeys_assets` (2).
- Per-file totals: billing 10, catalog 11, customer-service 8,
  domains/ssl/backups 28, gateway 13, helpdesk 9, infra 8,
  ipam 11, portal-apis 20, portal-billing-extras 4,
  portal-signup 6, provisioning 18, security 14,
  modifications 11, subscriptions 10, release-health 7,
  release-journeys 5, release-journeys-assets 2.
- No failures, no errors, no skips.

## 4. How to reproduce

```bash
bench --site beaverbill.localhost migrate
bench --site beaverbill.localhost run-tests --app beaverbill
cd frontend && npm run build && npm run type-check
python3 scripts/beaverbill_phase_check.py phase-14
```

## 5. Gaps recorded honestly

- **Browser end-to-end**: not captured (no browser binary in
  this environment). Portal journeys run through the whitelisted
  API layer with session/ownership enforcement, not a real DOM.
- **Accessibility audit**: no automated a11y run; the portal
  uses frappe-ui components and keyboard-navigable routes, but
  this is unverified by tooling here.
- **Performance**: only a pricing smoke (100 quotes < 30 s);
  no load test against concurrent checkouts or schedulers.
- **Provider sandboxes**: simulated drivers only; Hetzner/OVH/
  cPanel/DirectAdmin/Proxmox live calls are untested here.
- Evidence: `docs/phase-14-testing.md`,
  `docs/evidence/phase-14-baseline.json`.
