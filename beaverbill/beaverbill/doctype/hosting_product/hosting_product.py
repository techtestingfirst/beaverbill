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
def calculate_total_price(product_name, config_options=None, addons=None, promo_code=None):
	"""
	Calculates the total price for a product with optional configurable options, addons, and promo code.
	config_options: list of dicts with {"option_name": "...", "qty": 1}
	addons: list of addon names
	"""
	product = frappe.get_doc("Hosting Product", product_name)
	base_price = float(product.price)
	total = base_price

	# Add configurable options
	if config_options:
		for opt in config_options:
			opt_doc = frappe.get_all("Hosting Configurable Option", filters={
				"product": product_name,
				"option_name": opt.get("option_name")
			}, fields=["price_per_unit", "option_type"])
			if opt_doc:
				price_per_unit = float(opt_doc[0].price_per_unit or 0)
				qty = float(opt.get("qty", 1)) if opt_doc[0].option_type == "Quantity" else 1
				total += price_per_unit * qty

	# Add addons
	if addons:
		for addon_name in addons:
			addon_doc = frappe.get_all("Hosting Product Addon", filters={
				"product": product_name,
				"addon_name": addon_name
			}, fields=["price"])
			if addon_doc:
				total += float(addon_doc[0].price or 0)

	# Apply promo code
	discount = 0.0
	if promo_code:
		promo = frappe.get_doc("Hosting Promo Code", promo_code)
		promo.validate_promo(product_name)
		if promo.discount_type == "Percentage":
			discount = total * (float(promo.discount_value) / 100.0)
		else:
			discount = float(promo.discount_value)
		
		total = max(0.0, total - discount)

	return {
		"base_price": base_price,
		"discount": discount,
		"total_price": total,
		"currency": product.currency
	}
