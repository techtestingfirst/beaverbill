import frappe
from frappe.model.document import Document
from frappe.utils import getdate, today

class HostingPromoCode(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		code: DF.Data
		discount_type: DF.Literal["Percentage", "Fixed Amount"]
		discount_value: DF.Float
		expiration_date: DF.Date | None
		is_recurring: DF.Check
		product_group_restriction: DF.Link | None
		usage_limit: DF.Int
		used_count: DF.Int
	# end: auto-generated types

	def validate_promo(self, product_name):
		# Check expiration
		if self.expiration_date and getdate(self.expiration_date) < getdate(today()):
			frappe.throw("Promo code has expired")

		# Check usage limit
		if self.usage_limit and (self.used_count or 0) >= self.usage_limit:
			frappe.throw("Promo code usage limit reached")

		# Check product group restriction
		if self.product_group_restriction:
			product = frappe.get_doc("Hosting Product", product_name)
			if product.product_group != self.product_group_restriction:
				frappe.throw(f"Promo code is only valid for product group: {self.product_group_restriction}")
