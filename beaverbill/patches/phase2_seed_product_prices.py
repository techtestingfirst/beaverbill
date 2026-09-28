"""Phase 2: seed versioned prices from legacy product prices.

Idempotent: only creates a version when none covers the product's own
billing cycle and currency. Values match legacy prices, so resolved
prices are unchanged.
"""

import frappe
from frappe.utils import today


def execute():
	for product in frappe.get_all(
		"Hosting Product", fields=["name", "billing_cycle", "currency", "price"]
	):
		exists = frappe.db.exists(
			"Hosting Product Price",
			{
				"product": product.name,
				"billing_cycle": product.billing_cycle,
				"currency": product.currency or "USD",
			},
		)
		if exists:
			continue
		frappe.get_doc(
			{
				"doctype": "Hosting Product Price",
				"product": product.name,
				"billing_cycle": product.billing_cycle,
				"currency": product.currency or "USD",
				"price": product.price,
				"effective_from": today(),
			}
		).insert(ignore_permissions=True)
