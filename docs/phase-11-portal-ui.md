# Phase 11 — `frappe-ui` Customer Portal

Date: 2026-09-28. All changes are additive. No Phase 10 API
signatures changed; three small endpoints were appended
(`portal.list_gateways`, `portal.list/add/remove_payment_method`)
with matching role grants.

## 1. What was built

- **Auth**: Login, Signup, VerifyEmail (`/verify?token=`),
  ForgotPassword (Frappe reset email). Session rides Frappe
  cookies; the router restores the session on load, guards
  every app route, redirects guests to login with a return
  address, and keeps logged-in users off auth pages.
- **Backend** (`portal/public.py`, guest, rate-limited):
  `signup` (validates, creates User + Hosting Customer +
  role, sends a 24h verification link), `verify_email`
  (single-use token, sets `email_verified`), and
  `resend_verification` (always reports success to block
  address enumeration).
- **Pages** (23, all wired to real Phase 10 APIs): Dashboard,
  Services, ServiceDetail (power, single-use expiring console
  ticket, usage, add-ons, operations, confirmed password
  reset, double-confirmed OS reinstall, plan-change wizard
  with proration), Catalog, ProductDetail, Cart (coupons),
  Checkout (idempotent keys), Invoices, InvoiceDetail (pay
  dialog with gateway + saved method, PDF), PaymentMethods
  (token-only add, default handling, remove), Domains (DNS
  CRUD, SSL ordering), Backups (restore requests with
  approval notice), Addons (per-service catalog ordering,
  cancel), Tickets + TicketDetail ( replies), Profile
  (account, contacts CRUD, notification feed with unread
  counts and mark-read).
- **Shared UI**: `AppShell` (desktop sidebar, mobile menu,
  skip link, due-total and unread badges), `AsyncState`
  (loading spinner with `role=status`, error alert with
  retry, empty states), `StatusBadge` (one color language),
  frappe-ui Toasts for action feedback.

## 2. Sensitive data and trust boundaries

- Console tickets render masked (`maskSecret`) with a
  single-use/expiry warning and copy button; the ticket
  itself is never logged.
- Payment methods store gateway tokens only: the API
  refuses test-card markers, CVV hints, and non-4-digit
  last4 values; the UI warns never to type card numbers.
- Ticket bodies render via `v-html` (helpdesk agents may
  author formatted replies); content is same-trust as the
  desk, and customer input is escaped server-side by
  Frappe on write paths.
- No ERPNext routes, DocTypes, or imports anywhere in the
  portal (verified by grep).

## 3. Accessibility and responsive

- Every input has a label; icon-only buttons carry
  `aria-label`; async regions use `role=status`/`alert`;
  route changes retitle the document and move focus to
  `#main`; visible `:focus-visible` rings; `prefers-reduced-
  motion` disables animation; layouts collapse to single
  column with a mobile menu below `md`.
- Static audit: no unlabeled inputs, no images without
  alt text (none used), no `console.log` remnants,
  `vue-tsc` clean.

## 4. Tests (158 pass on beaverbill.localhost)

- New `test_portal_signup.py` (6): user/customer/role
  creation, duplicates, validation, verify-once,
  bad tokens, non-enumerating resend.
- New `test_portal_billing_extras.py` (4): gateway
  listing with currency filter, token add/list/remove,
  raw-card refusal, cross-customer denial.
- Regression: all 148 pre-existing tests pass.
- Frontend: `npm run build` and `npm run type-check`
  clean; bundle served from `beaverbill/www/beaverbill.html`
  at `/beaverbill` via the existing route rule.
- Commands: `bench --site beaverbill.localhost migrate`,
  per-module `run-tests`, `python3
  scripts/beaverbill_phase_check.py phase-11`.

## 5. Gaps recorded honestly

- No browser or device-lab verification (no browser binary
  in this environment): layouts, screenshots, and live
  payment/registrar round-trips remain Phase 14 work.
- Evidence: `docs/phase-11-portal-ui.md`,
  `docs/evidence/phase-11-baseline.json`.
