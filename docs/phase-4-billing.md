# Phase 4 — Billing, Invoices, Credits, and Financial Ledger

Date: 2026-09-28. Beaver Bill owns all billing records. No ERPNext
accounting is used or referenced. All changes are additive to earlier phases.

## 1. Records

- `Hosting Order`: status now covers Draft, Confirmed, Payment Pending,
  Pending (legacy default), Paid, Processing, Completed, Cancelled.
  Pending still works. New optional fields: `hosting_customer`,
  `idempotency_key`, `cancellation_reason`.
- `Hosting Invoice`: status now covers Draft, Issued, Partially Paid, Paid,
  Overdue, Cancelled, Written Off, plus legacy Unpaid. New invoices start
  as Draft and move to Issued. New fields: `items` (child table),
  `paid_amount`, `outstanding_amount`, `hosting_customer`,
  `idempotency_key`, `source_type`, `source_name`, `reversal_of`,
  `reversal_reason`, `cancellation_reason`, `invoice_pdf`.
  Invoice numbers use `INV-{####}`. Old Unpaid rows still allocate.
- `Hosting Invoice Item`: child table with product, description, qty,
  unit price, discount, tax, line total, billing cycle snapshot, and
  price snapshot JSON. Read-only snapshot fields freeze the line.
- `Hosting Payment Transaction`: Created, Authorized, Captured, Failed,
  Refunded, Partially Refunded, Chargeback. Gateway reference and
  idempotency key are unique.
- `Hosting Payment Allocation`: links one payment to one invoice with an
  amount, date, idempotency key, and reversal link.
- `Hosting Refund`: Created, Processed, Failed, Chargeback. Links payment
  and invoice, posts a ledger credit, updates the payment status.
- `Hosting Credit Note` and `Hosting Debit Note`: Draft, Issued, Applied,
  Cancelled. Each carries an idempotency key and reversal link.
- `Customer Credit Transaction`: adds `hosting_customer`, `currency`,
  `balance_after`, `source_type`, `source_name`, `reversal_of`, and
  `idempotency_key`. The old `amount` sum still gives the wallet balance.

## 2. Engine (`beaverbill/beaverbill/billing.py`)

- `issue_invoice`: builds lines with frozen snapshots, sets totals,
  paid 0, outstanding total, then moves Draft to Issued. Idempotent by key.
- `allocate_payment`: locks both docs, rejects non-captured payments,
  rejects amounts above outstanding, writes the allocation row, updates
  paid and outstanding, sets Paid or Partially Paid. Idempotent by key.
- `post_ledger`: appends one signed row with `balance_after`. Old code
  summed `amount`. New code also checks the chain. Idempotent by key.
- `apply_credit_to_invoice`, `create_credit_note`, `apply_credit_note`,
  `create_debit_note`, `process_refund`: each validates amounts and
  states, writes source links, keeps the ledger in sync.
- `cancel_invoice` needs a reason and refuses Paid or Written Off rows.
  `write_off_invoice` needs a reason and refuses Paid, Cancelled, or
  Written Off rows.
- `generate_invoice_pdf`: renders the Standard print to a private File
  and links it on `invoice_pdf`.
- `outstanding_invoices` and `ledger_mismatches`: back the two reports.
- `mark_overdue`: moves Issued and Partially Paid rows past due date
  to Overdue.

## 3. Compatibility

- `HostingOrder.process_payment` keeps its signature and result. It now
  writes `paid_amount` and `outstanding_amount` on the invoice.
- `get_customer_wallet_balance` in subscriptions still sums `amount`.
  `billing.get_ledger_balance` returns the same sum.
- Order Pending and invoice Unpaid remain valid inputs and transitions.
- All new fields are optional. Old rows migrate without a patch.

## 4. Reports

- `Invoice Outstanding`: open invoices with total, paid, outstanding,
  status, due date.
- `Credit Ledger Mismatch`: ledger rows where `balance_after` differs
  from the running sum. Empty when the ledger is clean.

## 5. Tests (58 pass on beaverbill.localhost)

- `bench --site beaverbill.localhost run-tests --module
  beaverbill.beaverbill.tests.test_billing_ledger`: 10 pass.
- Full app: 48 tests in `beaverbill/tests` plus 16 pre-existing doctype
  tests, all OK.
- New `test_billing_ledger` (10): order transitions plus legacy Pending
  path, invoice snapshots and Paid freeze, full and partial allocation
  with idempotent retry, over-allocation throw, legacy Unpaid allocate,
  credit note apply with ledger check, refund with payment update,
  cancel and write-off rules, overdue marking with report rows,
  `process_payment` compat.

## 6. Gaps recorded honestly

- Browser evidence for billing screens: not captured (no browser
  binary in this environment).
- Invoice PDF rendering is stored through `generate_invoice_pdf` but
  has no print-design review yet.
- Evidence: `docs/phase-4-billing.md`,
  `docs/evidence/phase-4-baseline.json`.
- Commands: `bench --site beaverbill.localhost migrate`,
  `bench --site beaverbill.localhost run-tests --app beaverbill`,
  `python3 scripts/beaverbill_phase_check.py phase-4`.
