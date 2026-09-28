# Phase 13 — Security and Compliance

Date: 2026-09-28. All changes are additive. No existing DocType,
field, hook, API signature, or workflow was renamed or removed.
The Phase 10 portal guard, permission hooks, webhook pipeline, and
console tickets keep their behavior; this phase adds a central
`security.py` helper, two staff-only records, and validators wired
into the provider-account controller. Token, session, and
login-throttle helpers live in `security_tokens.py`.

## 1. Role and permission matrix

`beaverbill/beaverbill/security.py::ROLE_MATRIX` (read it with
`get_role_matrix()`) documents every role:

- **System Manager**: full desk, user management, credential
  rotation, audit view, event replay, portal.
- **Hosting Admin**: desk, credential rotation, audit view, event
  replay. No user management, no portal customer context.
- **Hosting Support**: desk read/support, audit view. No
  credential management, no event replay.
- **Hosting Customer**: portal only, no desk. Every customer read
  or write passes an ownership check.
- **Guest**: public webhook and signup/verify endpoints only.

Staff privilege separation is enforced in three places: the
DocType permission tables (e.g. `Hosting Provider Account` grants
write only to Hosting Admin; Hosting Support is read-only),
`security.require_roles` / `can_manage_credentials`, and the
desk `get_public_fields` allowlist which never returns secrets.

## 2. Server-side permission and ownership checks

- Every portal endpoint resolves the caller through the Frappe
  session (`portal_customer`) and validates ownership
  (`own_service_or_throw`, `own_domain_or_throw`,
  `own_invoice_or_throw`, `own_subscription_or_throw`).
- Row-level `permission_query_conditions` plus `has_permission`
  hooks in `beaverbill/beaverbill/permissions.py` cover all
  customer-visible DocTypes. Cross-customer reads return
  `PermissionError` and are audited as `Denied`.
- New records are staff-only by default:
  `security_audit_log_query_conditions`,
  `scoped_api_token_query_conditions`, and `check_staff_only`
  return `1=0` / `False` for any non-staff user. Wired in
  `beaverbill/hooks.py` without touching existing entries.

## 3. Sensitive-action audit logs

`Security Audit Log` (user, action, status, detail, at) records
credential rotations/views, role changes, session revocations,
token issue/revoke, console issue/redeem, refunds, restore
requests, OS reinstalls, password resets, webhook replays, and
sync retries. Rows are immutable (`validate` refuses updates).
Details pass through `scrub_text` so secrets never land in logs.
Portal traffic keeps its existing `Portal Audit Event` stream.

## 4. Identity: verification, password reset, MFA, sessions, tokens

- **Email verification**: signup mints a 24-hour random token in
  `portal/public.py`; `verify_email` marks
  `Hosting Customer.email_verified`. Unverified logins keep
  portal access but the flag gates sensitive actions.
- **Password reset** reuses the Frappe session endpoints (no
  custom password handling, no password storage in Beaver Bill).
- **MFA**: administrator MFA and optional customer MFA ride on
  Frappe core Two Factor Authentication; `get_session_policy()`
  publishes this plus TTLs and the revocation entry point.
- **Sessions**: 12-hour TTL policy; `revoke_user_sessions(user)`
  (staff-only) drops `tabSessions` rows and the session cache,
  then audit-logs the count.
- **Scoped API tokens**: `Scoped API Token` stores only a prefix
  and a SHA-256 hash plus scopes, expiry, revocation, and
  last-used time. `issue_scoped_token` / `verify_scoped_token` /
  `revoke_scoped_token` enforce hash match, expiry, revocation,
  and scope. Raw tokens are shown once at issue time.

## 5. Secrets: encryption, rotation, scrubbing

- Provider `api_key` / `api_secret` are Frappe `Password` fields
  (encrypted at rest); code reads them only through
  `get_password`. `get_public_fields` exposes name/type/URL only.
- `rotate_provider_credential` (staff with credential rights)
  records a rotation event with no secret material.
- `safe_summary` (provisioning drivers), `scrub_text`, and
  `scrub_secrets` redact `api_key`, `api_secret`, `password`,
  `token`, `webhook_secret`, `private_key`, and card fields in
  logs, request hashes, and evidence. Evidence files were
  scanned for secrets before commit.

## 6. Web surface: CSRF, CORS, CSP, throttling, uploads

- **CSRF**: state-changing portal calls send the Frappe
  `csrf_token` (`www/beaverbill.py` boot object); guest webhook
  intake requires HMAC-SHA256 signatures, not cookies.
- **CORS**: no wildcard origins; the portal is same-origin and
  `frappe-ui` uses the session cookie plus CSRF token.
- **CSP/headers**: `get_security_headers()` emits
  `Content-Security-Policy` (`default-src 'self'`),
  `X-Content-Type-Options: nosniff`, `X-Frame-Options:
  SAMEORIGIN`, and a strict `Referrer-Policy`.
- **Rate limiting and login throttling**: per-endpoint
  sliding-window limits (`portal_endpoint`) plus
  `check_login_throttle` / `record_login_attempt`, which lock a
  login for 15 minutes after 5 failures in 15 minutes.
- **Uploads**: `validate_upload` allowlists `.png/.jpg/.jpeg/
  .pdf/.txt/.log` with matching MIME types, a 5 MB cap, and
  rejects path traversal. Used by the ticket-attachment path.

## 7. Injection and upstream-response hardening

- **SSRF**: `validate_outbound_url` accepts only http/https,
  blocks `localhost`, metadata hosts, private/loopback/link-local
  IPs, and non-standard ports. Enforced on
  `Hosting Provider Account.validate` (endpoint_url).
- **Command injection**: no `os.system`, `subprocess`, or shell
  templating anywhere in the app; driver calls are Python method
  dispatch through `call_driver_action`. Verified by scan.
- **Provider responses**: `validate_provider_response` accepts
  only small plain dicts with scalar values; anything else is a
  `ValidationError`, never persisted or rendered raw.
- **Console URLs**: 15-minute single-use tickets bound to the
  issuing user; `console_ticket` redeems exactly once and denies
  other sessions. Issuance and redemption are auditable.
- **Databases and backups**: backups are server-side files with
  staff-only desk access; restore requests need authorization
  (`Restore Request` ownership checks); no DB credentials in the
  repo or evidence.

## 8. OWASP ASVS spot-checks (Level 1, applicable items)

- 2.1/2.2 credential storage and rotation: Password fields,
  rotation log, no password logging — pass.
- 3.x session binding, expiry, revocation — pass.
- 4.x access control: ownership on every customer object,
  staff-only security records, deny-by-default — pass.
- 5.x input validation: uploads, URLs, provider payloads,
  idempotency keys with confirmation gates — pass.
- 7.x logging: audit events without secrets, immutable
  security log — pass.
- 9.x communications: HMAC webhooks, token-only payment
  references, hashed API tokens — pass.

## 9. Tests (new `test_security_compliance.py`, 14 cases)

Role separation, `require_roles` denial, cross-customer denial,
audit-log immutability plus secret scrubbing, staff-only record
hiding, token issue/verify/scope-denial/revoke/expiry,
customer-cannot-issue, secret scrubbing, upload allowlist,
SSRF blocklist, provider-response shape, login-throttle lock,
and session-policy/header shape. Run:

```bash
bench --site beaverbill.localhost migrate
bench --site beaverbill.localhost run-tests --app beaverbill \
  --test test_security_compliance
python3 scripts/beaverbill_phase_check.py phase-13
```

## 10. Gaps recorded honestly

- Browser evidence: not captured (no browser binary on this box).
- MFA is Frappe-core configuration, verified by policy reference
  rather than a live two-factor round-trip here.
- No live penetration test; ASVS review is a code-level
  checklist, not a third-party assessment.
- Unresolved risks accepted: provider sandbox APIs are trusted
  TLS endpoints (pinning deferred); backup encryption at rest
  depends on host disk policy (Phase 16 to define); rate-limit
  counters live in cache and reset on cache flush.
- Evidence: `docs/phase-13-security.md`,
  `docs/evidence/phase-13-baseline.json`.
