import frappe
from frappe.model.document import Document

class HostingProduct(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		billing_cycle: DF.Literal["Monthly", "Quarterly", "Semi-Annually", "Annually", "Biennially", "Triennially"]
		currency: DF.Link | None
		description: DF.Text | None
		price: DF.Currency
		product_group: DF.Link
		product_name: DF.Data
	# end: auto-generated types

	pass

@frappe.whitelist()
def calculate_total_price(
	product_name: str,
	config_options: list | None = None,
	addons: list | None = None,
	promo_code: str | None = None,
	billing_cycle: str | None = None,
	on_date: str | None = None,
	customer: str | None = None,
	target_currency: str | None = None,
	order_context: dict | None = None,
):
	"""
	Calculates the total price for a product with optional configurable options, addons, and promo code.
	config_options: list of dicts with {"option_name": "...", "qty": 1}
	addons: list of addon names

	The first four parameters keep the original signature and return shape.
	Extra keyword parameters add versioned pricing, tax, FX, and snapshots.
	"""
	from beaverbill.beaverbill.pricing import calculate_price

	result = calculate_price(
		product_name,
		config_options=config_options,
		addons=addons,
		promo_code=promo_code,
		billing_cycle=billing_cycle,
		on_date=on_date,
		customer=customer,
		target_currency=target_currency,
		order_context=order_context,
	)
	return {
		"base_price": result["base_price"],
		"discount": result["discount"],
		"total_price": result["subtotal"],
		"currency": result["currency"],
		"tax_total": result["tax_total"],
		"grand_total": result["total_price"],
		"billing_cycle": result["billing_cycle"],
		"price_source": result["price_source"],
		"snapshot": result["snapshot"],
	}
