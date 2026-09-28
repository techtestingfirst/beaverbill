# Phase 2 — Catalog, Pricing, Tax, and Discount Compatibility

Date: 2026-09-28. All changes are additive. `calculate_total_price` keeps its
signature; old return keys keep their meaning (`total_price` is still the
pre-tax line total). `validate_promo(product_name)` still works; the context
argument is optional.

## 1. New DocTypes (System Manager only, as with existing catalog types)

- `Hosting Product Price`: product, billing cycle, currency, price,
  effective from/to. Indexed on (product, cycle, currency, from).
- `Hosting Tax Rule`: name (unique), country (blank = all), state code,
  GST mode (None / CGST + SGST / IGST), product group (blank = all),
  rate %, effective from/to, active flag.
- `Hosting Customer Tax Profile`: user (unique), country, state, tax exempt,
  GSTIN.
- `Hosting Currency Exchange Rate`: from/to currency, rate (multiply),
  effective date. Indexed on (from, to, date).
- `Hosting Promo Redemption`: promo, customer, order, discount given —
  the usage ledger. Indexed on promo.

## 2. Schema additions to existing types (all optional)

- `Hosting Promo Code.applies_to`: All Orders (default) / First Order Only /
  Renewals Only / Upgrades Only.
- `Hosting Order Item`: `base_price`, `discount_amount`, `billing_cycle`,
  `calculation_snapshot` (JSON, read-only).
- `Hosting Invoice`: `subtotal`, `discount_amount`, `tax_amount`,
  `pricing_snapshot` (JSON, read-only). Full invoice-line tables arrive in
  Phase 4.

## 3. Pricing engine (`beaverbill/beaverbill/pricing.py`)

- Versioned lookup: newest version with effective_from <= date and no (or
  future) effective_to wins; otherwise the legacy product price and currency.
- Money: per-currency precision (JPY-style zero-decimal set, else 2),
  half-up rounding. FX: latest rate on/before the date, inverse fallback,
  throw when no rate exists.
- Tax: rules filtered by group, country, dates; exempt profiles skip all;
  India CGST + SGST splits only intra-state, IGST only inter-state.
- `redeem_promo`: locks the promo row (`for_update`), re-validates limit and
  restrictions against locked state, increments, writes the ledger row.
- Snapshot: every calculation returns a JSON breakdown (lines, discount, tax
  parts, source) storable on order items and invoices.

## 4. Migration

- `beaverbill.patches.phase2_seed_product_prices` (post_model_sync):
  creates one version per product from its legacy price/cycle/currency when
  none exists. Idempotent; ran on `beaverbill.localhost`.

## 5. Tests (46 pass on beaverbill.localhost)

- `bench --site beaverbill.localhost run-tests --app beaverbill`: 30
  integration + 16 pre-existing, all OK. Pre-existing promo/order tests pass
  unchanged against the wrapper.
- New `test_catalog_pricing` (11): legacy fallback, versioned preference and
  effective dates, CGST + SGST split, IGST out-of-state, exempt profile, FX
  conversion/inverse/rounding, first/renewal/upgrade restrictions, limit-1
  double redeem (second throws, count stays 1, one ledger row), snapshot
  contents, order-item/invoice snapshot fields, patch idempotency.
- Isolation note: tests in one class share a transaction, so fixtures are
  wiped in `setUp` (delete-then-create), matching the existing suites.

## 6. Gaps recorded honestly

- Catalog browser evidence: not captured (no browser binary in this
  environment). Desk forms render from DocType metadata; capture pending.
- Evidence: `docs/phase-2-catalog.md`, `docs/evidence/phase-2-baseline.json`.
- Commands: `bench --site beaverbill.localhost migrate`,
  `bench --site beaverbill.localhost run-tests --app beaverbill`,
  `python3 scripts/beaverbill_phase_check.py phase-2`.
