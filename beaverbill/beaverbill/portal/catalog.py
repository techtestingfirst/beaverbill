"""Phase 10 portal: catalog, configuration, and coupon validation."""

import frappe

from beaverbill.beaverbill import pricing
from beaverbill.beaverbill.portal.guard import portal_endpoint


@frappe.whitelist()
@portal_endpoint("portal.list_products", limit=120)
def list_products(product_group: str | None = None, currency: str | None = None) -> dict:
	"""Public catalog listing with current versioned prices."""
	filters = {}
	if product_group:
		filters["product_group"] = product_group
	rows = frappe.get_all(
		"Hosting Product",
		filters=filters,
		fields=["name", "product_name", "product_group", "billing_cycle", "price", "currency", "description"],
		order_by="product_name asc",
	)
	items = []
	for row in rows:
		if currency and row.currency != currency:
			try:
				converted = pricing.convert(float(row.price or 0), row.currency, currency)
			except Exception:
				continue
			row = dict(row)
			row["price"] = converted
			row["currency"] = currency
		items.append(row)
	return {"products": items}


@frappe.whitelist()
@portal_endpoint("portal.get_product", limit=120)
def get_product(product: str, billing_cycle: str | None = None) -> dict:
	"""Product detail with options, addons, specs, and live price."""
	doc = frappe.get_doc("Hosting Product", product)
	options = frappe.get_all(
		"Hosting Configurable Option",
		filters={"product": doc.name},
		fields=["name", "option_name", "option_type", "price_per_unit"],
	)
	addons = frappe.get_all(
		"Hosting Product Addon",
		filters={"product": doc.name},
		fields=["name", "addon_name", "price"],
	)
	unit = pricing.resolve_unit_price(doc.name, billing_cycle)
	cycles = pricing.list_cycle_prices(doc.name)
	return {
		"name": doc.name,
		"product_name": doc.product_name,
		"product_group": doc.product_group,
		"billing_cycle": unit.get("billing_cycle"),
		"price": unit.get("amount"),
		"currency": unit.get("currency"),
		"price_source": unit.get("source"),
		"billing_cycles": cycles,
		"description": doc.description,
		"specs": {
			"cpu_cores": doc.get("cpu_cores"),
			"ram_mb": doc.get("ram_mb"),
			"disk_gb": doc.get("disk_gb"),
			"bandwidth_gb": doc.get("bandwidth_gb"),
		},
		"options": options,
		"addons": addons,
	}


@frappe.whitelist()
@portal_endpoint("portal.validate_coupon", limit=60)
def validate_coupon(code: str, product: str, billing_cycle: str | None = None) -> dict:
	"""Dry-run a coupon against a product without consuming it."""
	name = frappe.db.get_value("Hosting Promo Code", {"code": code}, "name")
	if not name:
		frappe.throw("Unknown coupon code", frappe.ValidationError)
	quote = pricing.calculate_price(product, promo_code=name, billing_cycle=billing_cycle,
									order_context="Portal")
	return {
		"code": code,
		"valid": True,
		"discount": quote["discount"],
		"subtotal": quote["subtotal"],
		"tax_total": quote["tax_total"],
		"total_price": quote["total_price"],
		"currency": quote["currency"],
	}
