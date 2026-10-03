"""Phase 10 portal: cart, checkout, and orders."""

import json

import frappe

from beaverbill.beaverbill import billing as ledger
from beaverbill.beaverbill import pricing
from beaverbill.beaverbill import settings as bb_settings
from beaverbill.beaverbill.notifications import billable_customer
from beaverbill.beaverbill.portal.guard import is_staff, portal_customer, portal_endpoint

CART_TTL = 7 * 24 * 3600


def _cart_ttl() -> int:
	return bb_settings.get_int("cart_ttl_days", 7) * 24 * 3600


def _cart_key(user=None) -> str:
	return f"portal-cart:{user or frappe.session.user}"


def _load_cart(user=None) -> dict:
	raw = frappe.cache().get_value(_cart_key(user))
	if not raw:
		return {"items": [], "coupon": None}
	try:
		cart = json.loads(raw)
		cart.setdefault("items", [])
		return cart
	except ValueError:
		return {"items": [], "coupon": None}


def _save_cart(cart: dict, user=None) -> dict:
	frappe.cache().set_value(_cart_key(user), json.dumps(cart, default=str), expires_in_sec=_cart_ttl())
	return cart


def _promo_name(code: str | None) -> str | None:
	if not code:
		return None
	name = frappe.db.get_value("Hosting Promo Code", {"code": code}, "name")
	if not name:
		frappe.throw("Unknown coupon code", frappe.ValidationError)
	return name


@frappe.whitelist()
@portal_endpoint("portal.get_cart", limit=120)
def get_cart() -> dict:
	"""Return the caller's cart with a live priced total."""
	return _priced_cart()


def _priced_cart(user=None) -> dict:
	user = user or frappe.session.user
	cart = _load_cart(user)
	lines = []
	total = 0.0
	subtotal = 0.0
	discount = 0.0
	tax_total = 0.0
	currency = None
	for item in cart["items"]:
		qty = float(item.get("qty") or 1)
		quote = pricing.calculate_price(
			item["product"], config_options=item.get("options"), addons=item.get("addons"),
			promo_code=_promo_name(cart.get("coupon")) if cart.get("coupon") else None,
			billing_cycle=item.get("billing_cycle"), customer=user,
			order_context={"is_first_order": True},
		)
		line_total = float(quote["total_price"]) * qty
		total += line_total
		subtotal += float(quote.get("subtotal") or 0) * qty
		discount += float(quote.get("discount") or 0) * qty
		tax_total += float(quote.get("tax_total") or 0) * qty
		currency = currency or quote["currency"]
		lines.append({"product": item["product"], "qty": item.get("qty") or 1, "unit_total": quote["total_price"], "line_total": round(line_total, 2),
			"subtotal": round(float(quote.get("subtotal") or 0) * qty, 2),
			"discount": round(float(quote.get("discount") or 0) * qty, 2),
			"tax": round(float(quote.get("tax_total") or 0) * qty, 2)})
	return {"items": lines, "coupon": cart.get("coupon"), "subtotal": round(subtotal, 2),
		"discount": round(discount, 2), "tax_total": round(tax_total, 2),
		"total": round(total, 2), "currency": currency or "USD"}


@frappe.whitelist()
@portal_endpoint("portal.cart_add", limit=60)
def cart_add(product: str, qty: int = 1, billing_cycle: str | None = None, options: str | None = None, addons: str | None = None) -> dict:
	"""Add a configured product to the cart (catalog must exist)."""
	frappe.get_doc("Hosting Product", product)
	qty = max(int(qty or 1), 1)
	cart = _load_cart()
	cart["items"].append({
		"product": product,
		"qty": qty,
		"billing_cycle": billing_cycle,
		"options": json.loads(options) if options else None,
		"addons": json.loads(addons) if addons else None,
	})
	_save_cart(cart)
	try:
		from beaverbill.beaverbill import carts as cart_trail

		cart_trail.track_activity(cart=_load_cart())
	except Exception:
		pass
	return _priced_cart()


@frappe.whitelist()
@portal_endpoint("portal.cart_remove", limit=60)
def cart_remove(index: int) -> dict:
	"""Remove a cart line by position."""
	cart = _load_cart()
	try:
		cart["items"].pop(int(index))
	except (IndexError, ValueError):
		frappe.throw("Unknown cart line", frappe.ValidationError)
	_save_cart(cart)
	return _priced_cart()


@frappe.whitelist()
@portal_endpoint("portal.cart_clear", limit=60)
def cart_clear() -> dict:
	"""Empty the cart."""
	_save_cart({"items": [], "coupon": None})
	return {"items": [], "coupon": None, "subtotal": 0.0, "discount": 0.0, "tax_total": 0.0, "total": 0.0, "currency": "USD"}


@frappe.whitelist()
@portal_endpoint("portal.cart_coupon", limit=60)
def cart_coupon(code: str | None = None) -> dict:
	"""Attach (validated) or detach a coupon."""
	cart = _load_cart()
	if code:
		_promo_name(code)
		cart["coupon"] = code
	else:
		cart["coupon"] = None
	_save_cart(cart)
	try:
		from beaverbill.beaverbill import carts as cart_trail

		cart_trail.track_activity(cart=_load_cart())
	except Exception:
		pass
	return _priced_cart()


def _own_order(name: str, user=None) -> object:
	doc = frappe.get_doc("Hosting Order", name)
	if is_staff(user):
		return doc
	customer = frappe.db.get_value("Hosting Customer", {"primary_user": user or frappe.session.user}, "name")
	if doc.customer == (user or frappe.session.user) or (customer and doc.hosting_customer == customer):
		return doc
	frappe.throw(f"Order {name} does not belong to this customer", frappe.PermissionError)
	return doc


@frappe.whitelist()
@portal_endpoint("portal.checkout", limit=10)
def checkout(
	idempotency_key: str,
	order_form: str | None = None,
	domain_mode: str | None = None,
	domain_name: str | None = None,
	tos_consented: bool = False,
	recurring_consented: bool = False,
	captcha_verified: bool = False,
) -> dict:
	"""Convert the cart into an order plus an Issued invoice. Idempotent."""
	user = frappe.session.user
	customer = portal_customer()
	if not idempotency_key:
		frappe.throw("idempotency_key is required", frappe.ValidationError)
	hit = frappe.db.get_value("Hosting Order", {"idempotency_key": idempotency_key}, "name")
	if hit:
		doc = _own_order(hit, user)
		return {"order": doc.name, "status": doc.status, "duplicate_request": True}
	form = None
	if order_form:
		form = frappe.get_doc("Hosting Order Form", order_form)
		if not form.is_active:
			frappe.throw(f"Order form {order_form} is not active", frappe.ValidationError)
		if form.require_tos and not tos_consented:
			frappe.throw("Terms of Service consent is required", frappe.ValidationError)
		if form.require_recurring_consent and not recurring_consented:
			frappe.throw("Recurring billing consent is required", frappe.ValidationError)
		if form.require_captcha and not captcha_verified:
			frappe.throw("Human verification is required", frappe.ValidationError)
		if not form.allow_coupon and _load_cart(user).get("coupon"):
			frappe.throw("Coupons are not allowed on this order form", frappe.ValidationError)
	clean_domain = None
	if domain_mode:
		if domain_mode not in ("register", "existing"):
			frappe.throw("domain_mode must be register or existing", frappe.ValidationError)
		if not domain_name:
			frappe.throw("domain_name is required with domain_mode", frappe.ValidationError)
		from beaverbill.beaverbill import domains as domain_engine

		clean_domain = domain_engine.normalize_domain(domain_name)
		if domain_mode == "register" and frappe.db.exists("Hosting Domain", {"domain_name": clean_domain}):
			frappe.throw(f"Domain {clean_domain} is already managed", frappe.ValidationError)
	cart = _load_cart(user)
	if not cart["items"]:
		frappe.throw("Cart is empty", frappe.ValidationError)
	promo = _promo_name(cart.get("coupon"))
	is_first = not frappe.db.exists("Hosting Order", {"hosting_customer": customer})
	lines = []
	currencies = set()
	for item in cart["items"]:
		quote = pricing.calculate_price(
			item["product"], config_options=item.get("options"), addons=item.get("addons"),
			promo_code=promo, billing_cycle=item.get("billing_cycle"), customer=customer,
			order_context={"is_first_order": is_first},
		)
		currencies.add(quote["currency"])
		qty = float(item.get("qty") or 1)
		lines.append({
			"product": item["product"],
			"qty": qty,
			"price": quote["total_price"],
			"total": round(float(quote["total_price"]) * qty, 2),
			"base_price": quote["base_price"],
			"discount_amount": quote["discount"],
			"tax_amount": round(float(quote.get("tax_total") or 0) * qty, 2),
			"tax_breakdown": quote.get("tax_breakdown"),
			"billing_cycle": quote["billing_cycle"],
			"calculation_snapshot": quote["snapshot"][:4000],
		})
	if len(currencies) > 1:
		frappe.throw(
			f"Cart mixes currencies ({', '.join(sorted(currencies))}). Check out each currency separately.",
			frappe.ValidationError,
		)
	currency = next(iter(currencies)) if currencies else "USD"
	total = round(sum(float(line["total"]) for line in lines), 2)
	order = frappe.get_doc(
		{
			"doctype": "Hosting Order",
			"customer": user,
			"hosting_customer": customer,
			"order_date": frappe.utils.today(),
			"status": "Draft",
			"promo_code": promo,
			"currency": currency,
			"total_amount": total,
			"items": lines,
			"idempotency_key": idempotency_key,
			"order_form": form.name if form else None,
			"domain_mode": domain_mode,
			"domain_name": clean_domain,
			"tos_consented": 1 if tos_consented else 0,
			"recurring_consented": 1 if recurring_consented else 0,
		}
	).insert()
	from beaverbill.beaverbill import fraud as fraud_engine

	screened = fraud_engine.screen_order(order.name)
	decision = screened.get("decision")
	if decision == "reject":
		order.status = "Cancelled"
		order.cancellation_reason = "Rejected by fraud screening"
		order.save()
		try:
			from beaverbill.beaverbill import carts as cart_trail

			cart_trail.mark_converted(user)
		except Exception:
			pass
		_save_cart({"items": [], "coupon": None}, user)
		return {"order": order.name, "status": order.status, "screening": decision,
				"total": total, "currency": currency}
	if decision in ("hold", "manual"):
		order.status = "Fraud Hold" if decision == "hold" else "Manual Review"
		order.save()
		try:
			from beaverbill.beaverbill import carts as cart_trail

			cart_trail.mark_converted(user)
		except Exception:
			pass
		_save_cart({"items": [], "coupon": None}, user)
		return {"order": order.name, "status": order.status, "screening": decision,
				"total": total, "currency": currency}
	if promo:
		pricing.redeem_promo(promo, order_context={"is_first_order": is_first}, customer=billable_customer(customer), order=order.name, discount_given=sum(float(line["discount_amount"] or 0) for line in lines))
	order.status = "Confirmed"
	order.save()
	order.status = "Payment Pending"
	order.save()
	order.reload()
	invoice = ledger.issue_invoice(
		billable_customer(customer),
		ledger.build_invoice_items(order),
		currency=currency,
		order=order.name,
		idempotency_key=f"{idempotency_key}-invoice",
	)
	try:
		from beaverbill.beaverbill import carts as cart_trail

		cart_trail.mark_converted(user)
	except Exception:
		pass
	_save_cart({"items": [], "coupon": None}, user)
	return {"order": order.name, "status": order.status, "invoice": invoice.name,
			"total": total, "currency": currency}


@frappe.whitelist()
@portal_endpoint("portal.list_orders", limit=60)
def list_orders() -> dict:
	"""List the caller's orders."""
	user = frappe.session.user
	customer = portal_customer()
	rows = frappe.get_all(
		"Hosting Order",
		filters={"hosting_customer": customer},
		fields=["name", "order_date", "status", "total_amount", "currency"],
		order_by="creation desc",
	)
	legacy = [] if customer else []
	if not is_staff(user):
		legacy = frappe.get_all(
			"Hosting Order",
			filters={"customer": user, "hosting_customer": ("in", ["", None])},
			fields=["name", "order_date", "status", "total_amount", "currency"],
			order_by="creation desc",
		)
	return {"orders": rows + legacy}


@frappe.whitelist()
@portal_endpoint("portal.get_order", limit=60)
def get_order(name: str) -> dict:
	"""Order detail with items (ownership enforced)."""
	doc = _own_order(name)
	return {
		"name": doc.name,
		"status": doc.status,
		"order_date": str(doc.order_date),
		"total_amount": float(doc.total_amount or 0),
		"currency": doc.currency,
		"order_form": doc.get("order_form"),
		"domain_mode": doc.get("domain_mode"),
		"domain_name": doc.get("domain_name"),
		"tos_consented": int(doc.get("tos_consented") or 0),
		"recurring_consented": int(doc.get("recurring_consented") or 0),
		"items": [
			{"product": r.product, "qty": r.qty, "price": float(r.price or 0), "total": float(r.total or 0), "billing_cycle": r.billing_cycle}
			for r in doc.items
		],
	}


