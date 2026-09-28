# Phase 5 — Payment Gateway and Webhook Reliability

Date: 2026-09-28. Beaver Bill rows stay the source of truth.
`frappe/payments` supplies checkout controllers for real providers.
All changes are additive to earlier phases.

## 1. Records

- `Hosting Payment Gateway`: name, provider (Test Gateway, Razorpay,
  Stripe), supported currencies, default currency, webhook secret
  (Password field, stored encrypted), active flag, maintenance mode,
  max retries, retry backoff minutes.
- `Hosting Payment Method`: customer, gateway, token reference, brand,
  last 4, expiry month and year, default flag. No card number, PAN, or
  CVV field exists on the type. Only token references are stored.
- `Hosting Payment Event`: gateway event id (unique), gateway, event
  type, payload SHA256, raw payload, signature flag, status (Received,
  Validated, Processed, Failed, Duplicate, Ignored), linked payment,
  attempts, last error, idempotency key.
- `Hosting Payment Transaction` gains optional fields: token reference,
  last gateway event id, retry count, next retry at, last error. Old
  rows read without change. Failed gains one new edge back to Created
  so a retry can start a new attempt.

## 2. Intents (`beaverbill/beaverbill/gateways.py`)

- `create_payment_intent` reads the amount from the invoice on the
  server. The caller passes no amount. Unknown invoices, zero balances,
  inactive gateways, and unsupported currencies throw before any row
  is written, except outage handling below.
- The intent writes a Created payment with the invoice as source, the
  token reference when a method is given, and an idempotency key. The
  provider order id lands in `gateway_reference`.
- `TestGatewayAdapter` runs offline for tests and local checkout.
  `PaymentsAppAdapter` delegates checkout URLs to the `frappe/payments`
  controller for Razorpay and Stripe. Remote fetch beyond stored events
  reports unknown so staff reconcile by hand.
- Event type maps per provider turn gateway responses into payment
  states. Capture, refund, and chargeback map to separate states.

## 3. Webhooks (`beaverbill/beaverbill/webhooks.py`)

- Public URL: `/api/method/beaverbill.beaverbill.webhooks.gateway_webhook`.
  It takes the gateway name, the raw body, and the signature header.
- Each delivery is verified with HMAC-SHA256 against the stored secret
  using a constant-time compare. Bad signatures store a Failed event
  and throw. No state changes.
- Each body must parse as a JSON object with a string id and type.
  Other shapes store nothing and throw.
- Each stored event keeps the payload SHA256. Repeat deliveries of one
  event id return the stored row and bump attempts. No second transition
  runs and no second allocation is written.
- Out-of-order delivery walks the payment forward one legal transition
  at a time. A capture for a Created payment passes through Authorized.
  Backward moves throw and mark the event Failed.
- Capture auto-allocates the source invoice through the Phase 4 ledger
  with an event-keyed idempotency key. Refunds write `Hosting Refund`
  rows. Chargebacks write a separate `Hosting Refund` with Chargeback
  status plus a ledger credit. Amounts must match the payment within
  one cent for authorize and capture events.
- Razorpay amounts convert from paise. Stripe amounts convert from
  cents. Stripe links through `metadata.beaverbill_payment`.
- `replay_payment_event` lets staff re-apply a Failed event after a
  fix. Processed events stay put.

## 4. Retry and outage

- `schedule_retry` marks a pre-capture payment Failed with an error,
  a retry count, and next retry at using exponential backoff.
- `retry_failed_payment` is staff only. It refuses terminal rows past
  max retries and rows not yet due, then starts a new Created attempt.
- Maintenance mode on the gateway simulates an outage. Intents and
  retries record a Failed row with a scheduled retry and raise
  `GatewayOutage`. No partial writes escape.

## 5. Reconciliation

- `reconcile_gateway` reports stuck payments with no processed event,
  processed events with no payment, and capture amount mismatches.
- `Gateway Reconciliation` shows these rows per gateway.
- `Unprocessed Webhooks` lists events in Received, Validated, or
  Failed with attempts and last error.
- Staff tools: `reconcile_now`, `retry_failed_payment`,
  `replay_payment_event`. Each checks for System Manager or Hosting
  Admin inside the function.

## 6. Tests (77 pass on beaverbill.localhost)

- `bench --site beaverbill.localhost run-tests --module
  beaverbill.beaverbill.tests.test_gateway_webhooks`: 13 pass.
- Full app: 61 tests in `beaverbill/tests` plus 16 pre-existing
  doctype tests, all OK.
- New tests (13): server-side intent amount, unsupported currency,
  authorize then capture with invoice allocation, bad signature with
  stored Failed event, bad schema, duplicate delivery with one
  allocation, out-of-order capture, refund and chargeback separation,
  retry with backoff and terminal limit, outage with Failed row and
  retry, token-only method storage, stuck payment in reconciliation,
  failed event fix plus replay.

## 7. Gaps recorded honestly

- Browser evidence for checkout screens: not captured (no browser
  binary in this environment).
- Real provider traffic was not sent. Razorpay and Stripe paths use
  their documented payload shapes and the `frappe/payments`
  controllers. Only the Test Gateway ran end to end.
- Evidence: `docs/phase-5-gateway.md`,
  `docs/evidence/phase-5-baseline.json`.
- Commands: `bench --site beaverbill.localhost migrate`,
  `bench --site beaverbill.localhost run-tests --app beaverbill`,
  `python3 scripts/beaverbill_phase_check.py phase-5`.
