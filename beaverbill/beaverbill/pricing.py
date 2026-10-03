"""Phase 2 pricing engine: versioned prices, tax, FX, promo redemption, snapshots.

`calculate_total_price` in hosting_product.py keeps its signature and return
shape and delegates here, so existing callers are unaffected.
"""

import json
from decimal import Decimal, ROUND_HALF_UP

import frappe
from frappe.utils import getdate, today

ZERO_DECIMAL_CURRENCIES = {"JPY", "KRW", "VND", "CLP", "XOF"}

CYCLE_ORDER = ("Monthly", "Quarterly", "Semi-Annually", "Annually", "Biennially", "Triennially")


def money(value, currency=None):
	"""Round to the currency precision (half up)."""
	places = 0 if (currency or "").upper() in ZERO_DECIMAL_CURRENCIES else 2
	quant = Decimal(1).scaleb(-places)
	return float(Decimal(str(value or 0)).quantize(quant, rounding=ROUND_HALF_UP))


def resolve_unit_price(product_name, billing_cycle=None, currency=None, on_date=None):
	"""Newest effective price version, else the legacy product price."""
	product = frappe.get_doc("Hosting Product", product_name)
	day = getdate(on_date) if on_date else getdate(today())
	filters = {
		"product": product_name,
		"effective_from": ["<=", day],
	}
	if billing_cycle or product.billing_cycle:
		filters["billing_cycle"] = billing_cycle or product.billing_cycle
	if currency or product.currency:
		filters["currency"] = currency or product.currency
	versions = frappe.get_all(
		"Hosting Product Price",
		filters=filters,
		fields=["price", "currency", "billing_cycle", "effective_from", "effective_to"],
		order_by="effective_from desc",
	)
	row = next(
		(
			v
			for v in versions
			if not v.effective_to or getdate(v.effective_to) >= day
		),
		None,
	)
	if row:
		return {
			"amount": float(row.price),
			"currency": row.currency,
			"billing_cycle": row.billing_cycle,
			"source": "versioned",
		}
	# Legacy fallback; also covers versions whose effective_to has passed.
	return {
		"amount": float(product.price),
		"currency": product.currency,
		"billing_cycle": billing_cycle or product.billing_cycle,
		"source": "legacy",
	}


def list_cycle_prices(
	product_name: str, currency: str | None = None, on_date=None
) -> list[dict]:
	"""All currently-effective billing cycles for a product, cheapest lookup per cycle.

	Collects distinct cycles from effective ``Hosting Product Price`` rows, plus
	the product's own ``billing_cycle`` as legacy fallback. Each entry is a
	resolved unit price so the portal can offer every purchasable cycle.
	"""
	product = frappe.get_doc("Hosting Product", product_name)
	day = getdate(on_date) if on_date else getdate(today())
	rows = frappe.get_all(
		"Hosting Product Price",
		filters={"product": product_name, "effective_from": ["<=", day]},
		fields=["billing_cycle", "currency", "effective_to"],
	)
	cycles: list[str] = []
	for row in rows:
		if row.effective_to and getdate(row.effective_to) < day:
			continue
		cycle = row.billing_cycle or product.billing_cycle
		if currency and row.currency and row.currency != currency:
			continue
		if cycle and cycle not in cycles:
			cycles.append(cycle)
	if product.billing_cycle and product.billing_cycle not in cycles:
		cycles.append(product.billing_cycle)
	order = {cycle: idx for idx, cycle in enumerate(CYCLE_ORDER)}
	cycles.sort(key=lambda c: (order.get(c, 99), c))
	entries = []
	for cycle in cycles:
		try:
			unit = resolve_unit_price(product_name, cycle, currency, on_date)
		except Exception:
			continue
		entries.append(
			{
				"billing_cycle": unit["billing_cycle"],
				"price": unit["amount"],
				"currency": unit["currency"],
				"price_source": unit["source"],
			}
		)
	return entries


def convert(amount, from_currency, to_currency, on_date=None):
	"""Convert with the latest effective rate on or before the date."""
	if not from_currency or not to_currency or from_currency == to_currency:
		return float(amount or 0)
	day = getdate(on_date) if on_date else getdate(today())
	rate = frappe.db.get_all(
		"Hosting Currency Exchange Rate",
		filters={"from_currency": from_currency, "to_currency": to_currency, "effective_date": ["<=", day]},
		fields=["rate"],
		order_by="effective_date desc",
		limit=1,
	)
	if rate:
		return float(amount or 0) * float(rate[0].rate)
	inverse = frappe.db.get_all(
		"Hosting Currency Exchange Rate",
		filters={"from_currency": to_currency, "to_currency": from_currency, "effective_date": ["<=", day]},
		fields=["rate"],
		order_by="effective_date desc",
		limit=1,
	)
	if inverse and float(inverse[0].rate):
		return float(amount or 0) / float(inverse[0].rate)
	frappe.throw(f"No exchange rate from {from_currency} to {to_currency} on {day}")


def get_tax_profile(user=None, customer=None):
	if customer:
		name = frappe.db.get_value("Hosting Customer Tax Profile", {"customer": customer}, "name")
		if name:
			return frappe.get_doc("Hosting Customer Tax Profile", name)
	name = frappe.db.get_value("Hosting Customer Tax Profile", {"user": user or frappe.session.user}, "name")
	return frappe.get_doc("Hosting Customer Tax Profile", name) if name else None


def applicable_tax_rules(product_group, profile, on_date=None):
	day = getdate(on_date) if on_date else getdate(today())
	rules = frappe.get_all(
		"Hosting Tax Rule",
		filters={"is_active": 1},
		fields=["name", "tax_name", "country", "state_code", "gst_mode", "product_group", "rate", "effective_from", "effective_to"],
	)
	matched = []
	for rule in rules:
		if rule.product_group and rule.product_group != product_group:
			continue
		if rule.country and (not profile or (profile.country or "") != rule.country):
			continue
		if rule.effective_from and getdate(rule.effective_from) > day:
			continue
		if rule.effective_to and getdate(rule.effective_to) < day:
			continue
		matched.append(rule)
	return matched


def compute_taxes(subtotal, product_group, profile, currency, taxable=True):
	"""Apply matching rules; split India GST by origin state.

	Blesta parity additive: taxable flag skips lines, reverse-charge
	zero-rates EU B2B, Inclusive back-calculates, Level 2 cascades on
	subtotal + Level 1. Return shape preserved.
	"""
	from beaverbill.beaverbill import taxes as tax_helper
	breakdown = []
	total = 0.0
	if not tax_helper.tax_enabled():
		return breakdown, total
	if not taxable:
		return breakdown, total
	if profile and profile.tax_exempt:
		return breakdown, total
	reverse = False
	try:
		reverse = tax_helper.is_reverse_charge(
			(profile.country if profile else "") or "",
			bool(profile and getattr(profile, "tax_id_validated", 0)),
		)
	except Exception:
		reverse = False
	level1_base = 0.0
	level1_total = 0.0
	for rule in applicable_tax_rules(product_group, profile, None):
		rate = float(rule.rate or 0)
		level = str(getattr(rule, "tax_level", "1") or "1")
		type_ = (getattr(rule, "tax_type", "Exclusive") or "Exclusive")
		if reverse:
			breakdown.append({"rule": rule.tax_name, "part": "reverse-charge", "rate": 0.0, "amount": 0.0})
			continue
		if rule.country == "India" and rule.gst_mode == "CGST + SGST":
			if not profile or profile.state != rule.state_code:
				continue
			half = money(subtotal * rate / 200.0, currency)
			breakdown.append({"rule": rule.tax_name, "part": "CGST", "rate": rate / 2, "amount": half})
			breakdown.append({"rule": rule.tax_name, "part": "SGST", "rate": rate / 2, "amount": half})
			total += half * 2
			level1_total += half * 2
			continue
		if rule.country == "India" and rule.gst_mode == "IGST":
			if profile and profile.state == rule.state_code:
				continue
			amount = money(subtotal * rate / 100.0, currency)
			breakdown.append({"rule": rule.tax_name, "part": "IGST", "rate": rate, "amount": amount})
			total += amount
			level1_total += amount
			continue
		if level == "2":
			base = subtotal + level1_total
			amount = money(base * rate / 100.0, currency)
			breakdown.append({"rule": rule.tax_name, "part": "L2", "rate": rate, "amount": amount})
			total += amount
			continue
		if type_ == "Inclusive":
			amount = money(subtotal * rate / (100.0 + rate), currency)
			breakdown.append({"rule": rule.tax_name, "part": "", "rate": rate, "amount": amount, "inclusive": True})
			continue
		amount = money(subtotal * rate / 100.0, currency)
		breakdown.append({"rule": rule.tax_name, "part": "", "rate": rate, "amount": amount})
		total += amount
		level1_total += amount
	level1_base = level1_total
	return breakdown, money(total, currency)


def calculate_price(
	product_name,
	config_options=None,
	addons=None,
	promo_code=None,
	billing_cycle=None,
	on_date=None,
	customer=None,
	target_currency=None,
	order_context=None,
):
	"""Full pricing breakdown with versioned price, discount, tax, FX, snapshot."""
	product = frappe.get_doc("Hosting Product", product_name)
	unit = resolve_unit_price(product_name, billing_cycle, target_currency if target_currency else None, on_date)
	currency = target_currency or unit["currency"]
	base_price = money(convert(unit["amount"], unit["currency"], currency, on_date), currency)
	total = base_price
	lines = [{"kind": "base", "label": product_name, "amount": base_price}]

	if config_options:
		for opt in config_options:
			found = frappe.get_all(
				"Hosting Configurable Option",
				filters={"product": product_name, "option_name": opt.get("option_name")},
				fields=["price_per_unit", "option_type"],
			)
			if found:
				qty = float(opt.get("qty", 1)) if found[0].option_type == "Quantity" else 1
				amount = money(convert(float(found[0].price_per_unit or 0) * qty, product.currency, currency, on_date), currency)
				total += amount
				lines.append({"kind": "option", "label": opt.get("option_name"), "qty": qty, "amount": amount})

	if addons:
		for addon_name in addons:
			found = frappe.get_all(
				"Hosting Product Addon",
				filters={"product": product_name, "addon_name": addon_name},
				fields=["price"],
			)
			if found:
				amount = money(convert(float(found[0].price or 0), product.currency, currency, on_date), currency)
				total += amount
				lines.append({"kind": "addon", "label": addon_name, "amount": amount})

	discount = 0.0
	if promo_code:
		promo = frappe.get_doc("Hosting Promo Code", promo_code)
		promo.validate_promo(product_name, order_context)
		if promo.discount_type == "Percentage":
			discount = money(total * (float(promo.discount_value) / 100.0), currency)
		else:
			discount = money(convert(float(promo.discount_value), product.currency, currency, on_date), currency)
		total = max(0.0, money(total, currency) - discount)

	from beaverbill.beaverbill import settings as _settings

	setup_fee = money(convert(float(getattr(product, "setup_fee", 0) or 0), product.currency, currency, on_date), currency)
	if setup_fee:
		total += setup_fee
		lines.append({"kind": "setup", "label": "Setup fee", "amount": setup_fee})
	subtotal = money(total, currency)
	tax_base = subtotal if _settings.get_int("tax_setup_fees", 1) == 1 else money(subtotal - setup_fee, currency)
	taxable = bool(int(getattr(product, "taxable", 1) if getattr(product, "taxable", 1) is not None else 1))
	if customer and frappe.db.exists("Hosting Customer", customer):
		profile = get_tax_profile(customer=customer)
	else:
		profile = get_tax_profile(user=customer)
	tax_breakdown, tax_total = compute_taxes(tax_base, product.product_group, profile, currency, taxable=taxable)
	grand = money(subtotal + tax_total, currency)
	result = {
		"base_price": base_price,
		"discount": discount,
		"subtotal": subtotal,
		"tax_breakdown": tax_breakdown,
		"tax_total": tax_total,
		"total_price": grand,
		"currency": currency,
		"billing_cycle": unit["billing_cycle"],
		"price_source": unit["source"],
		"lines": lines,
	}
	result["snapshot"] = json.dumps(result, default=str)
	return result


def redeem_promo(promo_code, product_name=None, order_context=None, customer=None, order=None, discount_given=0):
	"""Concurrency-safe redemption: lock, re-validate, increment, ledger."""
	locked = frappe.db.get_value(
		"Hosting Promo Code", promo_code, ["used_count", "usage_limit"], for_update=True
	)
	if locked is None:
		frappe.throw(f"Unknown promo code: {promo_code}")
	promo = frappe.get_doc("Hosting Promo Code", promo_code)
	promo.validate_promo(product_name, order_context)
	# Re-check the limit against the locked row: two racers cannot both pass.
	used, limit = (locked[0] or 0), locked[1]
	if limit and used >= limit:
		frappe.throw("Promo code usage limit reached")
	promo.used_count = used + 1
	promo.save(ignore_permissions=True)
	ledger = frappe.get_doc(
		{
			"doctype": "Hosting Promo Redemption",
			"promo_code": promo_code,
			"customer": customer or "",
			"order": order or "",
			"discount_given": discount_given or 0,
		}
	).insert(ignore_permissions=True)
	return ledger.name
