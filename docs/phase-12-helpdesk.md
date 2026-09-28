# Phase 12 — Helpdesk Integration

Date: 2026-09-28. All changes are additive. The portal ticket
 API keeps its signatures (three optional link params added)
 and the helpdesk app itself is untouched.

## 1. Deployment and source of truth

- **Same-site**: helpdesk runs on the same site, so tickets,
  customers, and statuses are native documents. No cross-site
  API, no credential sync.
- **Source of truth**: Beaver Bill `Hosting Customer` and
  `Hosting Customer Contact` rows are canonical. `HD
  Customer` rows (matched by email) and core-`Contact` +
  member rows are synced mirrors. Mapping state lives in
  `Helpdesk Sync Log`, never in helpdesk schema.

## 2. Records (both new)

- `Helpdesk Sync Log`: entity type (Customer/Contact/
  Ticket), entity, HD record, status (Pending/In Progress/
  Synced/Failed), attempts with backoff (5 min doubling,
  4 h cap, 5 tries), error taxonomy, unique idempotency
  key. Ticket rows are creation-time dedup markers.
- `Ticket Reference`: HD Ticket name (Data, so beaverbill
  installs without helpdesk) linked to customer, service,
  order, invoice, domain, opener, and time. One row per
  ticket.

## 3. Engine (`helpdesk_sync.py`)

- `sync_customer` / `sync_contact`: idempotent find-or-
  create (HD Customer by email; core Contact by email with
  HD link; member row appended once). Fault-injectable;
  failures park with retries; final failures surface in
  `sync_failures` and staff `sync_report` (also covers
  mail health and pending counts). `retry_sync` requeues.
- Scheduler `process_helpdesk_sync` runs due rows daily.
- Mapping: portal display names for HD statuses,
  `resolve_status/priority/team` with documented fallbacks,
  read-only `ticket_sla` (policy stays agent-owned).
- `create_portal_ticket`: ownership-validated links,
  attachment validation, raiser-Contact ensured **and**
  added as HD member (helpdesk validates ticket customers
  through members), idempotent by key, footer lists links
  for agents, opener notified.
- **Internal-note rule** (`visible_comments`): portal shows
  Frappe Comments plus HD Ticket Comments authored by the
  caller; agent-authored HD comments are internal-only.
  Staff see everything. Portal replies are Frappe Comments,
  never confusable with internal notes.
- `email_health`: reports inbound/outbound/default mail
  accounts. This site has none configured — inbound mail
  setup is documented here as an admin task, not code.

## 4. Portal changes

- `support.py` now delegates to the engine: linked ticket
  creation (service/order/invoice/domain), detail with
  links, SLA, and the visibility-filtered conversation.
- Signup grants `HD Customer` alongside `Hosting Customer`
  (only when helpdesk is present), so tickets are created
  as the user — the Phase 11 admin-context elevation is
  gone. Signup briefly elevates only to assign roles,
  since guests cannot edit User.
- Frontend `TicketDetail` shows linked records, the
  portal-facing status, and SLA dates.

## 5. Tests (167 pass on beaverbill.localhost)

- New `test_helpdesk_sync.py` (9): mirror idempotency for
  customers and contacts, fault then scheduler recovery,
  failure report plus staff retry, status/priority/team
  mapping, ticket creation with HD customer link and
  Ticket Reference, creation idempotency, internal-note
  hiding (customer vs staff views), cross-customer link
  and read denial, SLA snapshot, mail health shape,
  attachment refusal.
- Regression: all 158 pre-existing tests pass, including
  the 20 portal API and 6 signup tests against the
  rewritten ticket layer.
- Commands: `bench --site beaverbill.localhost migrate`,
  per-module `run-tests`, `python3
  scripts/beaverbill_phase_check.py phase-12`.

## 6. Gaps recorded honestly

- Browser evidence: not captured (no browser binary).
- No live mail round-trip: no mail accounts exist on this
  site, so inbound email is config-documented, not
  exercised. Agent-side workflows (assignment rules, SLA
  policies) stay helpdesk-native and untested here.
- Evidence: `docs/phase-12-helpdesk.md`,
  `docs/evidence/phase-12-baseline.json`.
