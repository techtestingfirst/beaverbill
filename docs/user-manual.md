# BeaverBill User Manual

Customer portal at `http://<site>/beaverbill` (local dev: `http://beaverbill.localhost:8000/beaverbill`). Staff/advanced runbooks live in `docs/guides.md`; business policies in `docs/policies.md`.

## 1. Getting started

1. Open `/beaverbill/signup` and create your account with full name, email, password.
2. Check your email for the verification link (valid 24 hours). Open it, or use `/verify`. Ask for a fresh link with resend if it expired.
3. Log in at `/beaverbill/login`. Unverified accounts can browse but cannot buy or manage services — verify first.
4. Forgot password: `/forgot-password` sends a reset link. Contact support if you lose access to the email itself.

Your data: one login owns one customer record. Keep `Profile` email/timezone current so invoices, renewal reminders, and expiry notices reach you.

## 2. Buying a service

1. **Browse** — `/catalog` lists product groups and plans; open a product (`/catalog/:name`) for price, billing cycle, options, addons.
2. **Configure** — pick options (CPU/RAM/disk, OS, region where offered) and optional addons. The quoted total includes tax preview where applicable.
3. **Coupon** — enter promo code in cart; invalid/expired/inapplicable codes show a reason and change nothing. First-order, renewal-only, or upgrade-only codes apply only to matching orders.
4. **Cart** — `/cart`: add, remove, clear. Cart is kept 7 days.
5. **Checkout** — `/checkout` → Place order. Safe to retry on network errors: repeats return the original order (`duplicate_request`) instead of charging twice. Result: confirmed order + ready invoice in the payment center.

Prices lock at order/invoice time (snapshot). Later price changes never rewrite your existing invoices.

## 3. Invoices and payments

- **Payment center** — `/invoices` lists Draft/Issued/Partially Paid/Paid/Overdue/Cancelled invoices. Open one (`/invoices/:name`) for lines, tax, totals, status, and PDF download.
- **Pay** — choose gateway + saved method or add a new one. Only gateway token references are stored; card numbers are never kept by BeaverBill. Track with payment status; paid invoices show Paid once the signed gateway webhook is processed (usually seconds; replay if stuck — ask support).
- **Saved methods** — `/payment-methods`: list, add, remove. Removing a method never affects already-paid invoices.
- **Partial payments** — an invoice can move to Partially Paid; pay the remainder the same way.
- **Overdue** — unpaid past due date becomes Overdue and starts dunning (see §8). Pay promptly to avoid suspension.
- **Refunds/credits** — refunds post as wallet credit by default (applied to future invoices automatically or on request) or back to the original method on request to billing staff. Duplicate gateway charges are refunded in full. Used time, consumed bandwidth/storage, domain registrations, and completed SSL validation work are not refundable.

## 4. Services dashboard

- `/` (Dashboard) and `/services` list services with status, plan, IP, subscription, renewal date.
- `/services/:name` (detail) shows product, billing cycle, IP address, domain, server node, subscription, recent operations, addons, usage.
- Statuses: `Pending → Provisioning → Active → (Modification Pending) → Suspended → Cancellation Pending → Terminated → Archived`. New orders provision automatically after payment; watch detail page until Active.

## 5. Running your server

On the service detail page:

- **Power** — Reboot / Power off / Power on. Each queues a tracked operation; status appears in recent operations. Only Active or Suspended services accept power actions.
- **Console** — open console to get a single-use link valid 15 minutes. If it expires or was already used, issue a fresh one. Needs provider console support (ask support if unavailable on your plan).
- **Password reset** — type the confirmation, submit. Needs confirmation + safe-retry key; check email/service for the new credential flow.
- **OS reinstall** — destructive: confirm twice and tick the data-loss acknowledgement. Back up first (see §7). Retries with the same key return the original request.
- **Change plan** (upgrade/downgrade) — pick a new product; `Immediate` bills the prorated difference now, `Next Cycle` applies at renewal with no invoice. Downgrades that shrink disk/limits are blocked when usage exceeds the target, and need the data-loss acknowledgement. Failed resizes never strand you: the request stays auditable and staff compensate.

## 6. Domains, DNS, SSL

`/domains` covers names, DNS, certificates.

- **Domains** — view your names, expiry, auto-renew flag, registrar status. Keep `auto_renew` on; renewal invoices go out before expiry and paid renewals process within 7 days of expiry (USD 15/year standard). Expired names get a 30-day grace with reminders; after that the registry may delete the name permanently.
- **DNS** — add/remove records (A/AAAA/CNAME/TXT/MX…). For SSL validation add the `_acme-challenge` TXT shown and re-validate.
- **SSL** — request a certificate for an owned service + domain; validation is DNS-challenge based, validity 90 days, renewal automatic with daily monitoring. Failed renewals notify you — fix DNS and it retries.
- Transfers need a valid auth code and re-register one year at the registry.

## 7. Backups and restores

`/backups`:

- Policies default to daily backups keeping 7 copies / 30 days; per-service overrides possible (ask support).
- Restores are two-step by design: request restore → staff approval → execute. Restores overwrite target data — confirm twice and verify which backup and target you picked.
- Storage overage (usage above included quota) is metered and invoiced once per snapshot — it never auto-suspends; sustained overage triggers a notice plus an upgrade suggestion.
- Backups of terminated services expire with their policy inside the 30-day post-termination window.

## 8. Renewals, failed payments, suspension

- Renewal invoices arrive ~3 days before period end. Funded payment methods and auto-renew domains renew automatically.
- Failed renewal: up to 4 retries (4-hour backoff) → 7-day grace → suspension (services power down, data kept) → termination if still unpaid.
- **Reinstatement** — pay the outstanding invoice, then ask staff to reinstate (available from failed/grace/suspended/cancellation-pending states).
- **Cancellation** — default is end-of-period (runs to period end, then terminates). Immediate cancel credits unused time to the wallet and schedules data purge 30 days out. After purge, recovery is impossible.
- Terminated services keep data 30 days, then purge.

## 9. Add-ons

`/addons`: order addons (backup packs, storage, SSL, IPs where offered), view status and renewal, cancel. Every addon follows the same order → invoice → renew → cancel lifecycle as base services.

## 10. Support tickets

`/tickets`: create with service/order/invoice/domain linked, priority (Low/Medium/High/Urgent → 24h/8h/4h/1h business-day response targets), message, attachments. Reply in `/tickets/:name`. Agent internal notes stay hidden by design — only your messages and agent replies show. SLA misses are credited on request.

## 11. Profile and security

`/profile`:

- Update name, contact details, locale, timezone, marketing consent (withdrawing stops marketing mail, not billing/security notices).
- Manage billing and technical contacts (add/update/delete).
- Use a strong unique password; never share logins. After any suspected compromise: change password, ask staff to revoke sessions and scoped tokens.
- Five wrong logins in 15 minutes locks login for 15 minutes; per-endpoint rate limits may ask you to wait and retry with backoff.

## 12. Troubleshooting

| Problem | What to do |
|---|---|
| No verification email | Check spam; resend from `/verify`; confirm profile email |
| Coupon rejected | Check code spelling, expiry, first-order/renewal-only limits; totals show without the coupon |
| Checkout retry / double-charge fear | Safe to retry — same key returns original order; check `/invoices` before paying again |
| Paid but invoice not Paid | Wait ~15 min for webhook; then contact support to replay the payment event |
| Power action stuck | Check recent operations on detail page; transient errors clear on retry; `Manual Review` needs staff |
| Console link invalid/expired | Issue a fresh link (15-min single-use) |
| Certificate failed validation | Add the `_acme-challenge` TXT record, re-validate |
| Restore stuck Pending | Needs staff approval — open a ticket |
| Ticket reply missing | May be an internal agent note (hidden by design) |
| Service suspended | Pay overdue invoice, then request reinstatement |
| Data gone after 30 days post-termination | Purged permanently; restores impossible — this is policy |

Still stuck: open a ticket from `/tickets` with the service/invoice name, what you clicked, and the exact error text.
