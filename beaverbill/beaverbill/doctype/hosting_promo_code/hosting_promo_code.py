import frappe
from frappe.model.document import Document
from frappe.utils import getdate, today

class HostingPromoCode(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		applies_to: DF.Literal["All Orders", "First Order Only", "Renewals Only", "Upgrades Only"]
		code: DF.Data
		discount_type: DF.Literal["Percentage", "Fixed Amount"]
		discount_value: DF.Float
		expiration_date: DF.Date | None
		is_recurring: DF.Check
		product_group_restriction: DF.Link | None
		usage_limit: DF.Int
		used_count: DF.Int
	# end: auto-generated types

	def validate_promo(self, product_name, order_context=None):
		# Check expiration
		if self.expiration_date and getdate(self.expiration_date) < getdate(today()):
			frappe.throw("Promo code has expired")

		# Check usage limit
		if self.usage_limit and (self.used_count or 0) >= self.usage_limit:
			frappe.throw("Promo code usage limit reached")

		# Check product group restriction (skipped when no product is in scope)
		if self.product_group_restriction and product_name:
			product = frappe.get_doc("Hosting Product", product_name)
			if product.product_group != self.product_group_restriction:
				frappe.throw(f"Promo code is only valid for product group: {self.product_group_restriction}")

		# Check order-type restriction (default All Orders keeps old promos valid everywhere)
		context = order_context or {}
		applies_to = self.applies_to or "All Orders"
		if applies_to == "First Order Only" and not context.get("is_first_order"):
			frappe.throw("Promo code is only valid for first orders")
		if applies_to == "Renewals Only" and not context.get("is_renewal"):
			frappe.throw("Promo code is only valid for renewals")
		if applies_to == "Upgrades Only" and not context.get("is_upgrade"):
			frappe.throw("Promo code is only valid for upgrades")
