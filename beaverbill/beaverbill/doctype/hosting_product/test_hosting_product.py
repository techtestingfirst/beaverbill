import frappe
import unittest
from beaverbill.beaverbill.doctype.hosting_product.hosting_product import calculate_total_price
from frappe.utils import add_days, today

class TestHostingProduct(unittest.TestCase):
	def setUp(self):
		frappe.db.delete("Hosting Product Addon")
		frappe.db.delete("Hosting Configurable Option")
		frappe.db.delete("Hosting Product")
		frappe.db.delete("Hosting Promo Code")
		frappe.db.delete("Hosting Product Group")

		self.group_vps = frappe.get_doc({
			"doctype": "Hosting Product Group",
			"product_group_name": "VPS Servers"
		}).insert()

		self.group_shared = frappe.get_doc({
			"doctype": "Hosting Product Group",
			"product_group_name": "Shared Hosting"
		}).insert()

		self.product = frappe.get_doc({
			"doctype": "Hosting Product",
			"product_name": "VPS Starter",
			"product_group": "VPS Servers",
			"billing_cycle": "Monthly",
			"price": 10.0,
			"currency": "USD"
		}).insert()

		self.option_ram = frappe.get_doc({
			"doctype": "Hosting Configurable Option",
			"option_name": "Extra RAM",
			"product": "VPS Starter",
			"option_type": "Quantity",
			"price_per_unit": 2.0
		}).insert()

		self.addon_backup = frappe.get_doc({
			"doctype": "Hosting Product Addon",
			"addon_name": "Daily Backups",
			"product": "VPS Starter",
			"price": 3.0
		}).insert()

	def test_base_pricing(self):
		res = calculate_total_price("VPS Starter")
		self.assertEqual(res["total_price"], 10.0)

	def test_config_options_and_addons(self):
		res = calculate_total_price(
			"VPS Starter",
			config_options=[{"option_name": "Extra RAM", "qty": 2}],
			addons=["Daily Backups"]
		)
		# 10.0 (base) + 2 * 2.0 (RAM) + 3.0 (Backup) = 17.0
		self.assertEqual(res["total_price"], 17.0)

	def test_percentage_promo_code(self):
		promo = frappe.get_doc({
			"doctype": "Hosting Promo Code",
			"code": "SAVE50",
			"discount_type": "Percentage",
			"discount_value": 50.0,
			"usage_limit": 10,
			"used_count": 0
		}).insert()

		res = calculate_total_price("VPS Starter", promo_code="SAVE50")
		self.assertEqual(res["total_price"], 5.0)
		self.assertEqual(res["discount"], 5.0)

	def test_fixed_promo_code(self):
		promo = frappe.get_doc({
			"doctype": "Hosting Promo Code",
			"code": "SAVE3",
			"discount_type": "Fixed Amount",
			"discount_value": 3.0,
			"usage_limit": 10,
			"used_count": 0
		}).insert()

		res = calculate_total_price("VPS Starter", promo_code="SAVE3")
		self.assertEqual(res["total_price"], 7.0)

	def test_expired_promo_code(self):
		promo = frappe.get_doc({
			"doctype": "Hosting Promo Code",
			"code": "EXPIRED",
			"discount_type": "Percentage",
			"discount_value": 10.0,
			"expiration_date": add_days(today(), -1),
			"usage_limit": 10,
			"used_count": 0
		}).insert()

		with self.assertRaises(frappe.ValidationError):
			calculate_total_price("VPS Starter", promo_code="EXPIRED")

	def test_promo_code_usage_limit(self):
		promo = frappe.get_doc({
			"doctype": "Hosting Promo Code",
			"code": "LIMIT1",
			"discount_type": "Percentage",
			"discount_value": 10.0,
			"usage_limit": 1,
			"used_count": 1
		}).insert()

		with self.assertRaises(frappe.ValidationError):
			calculate_total_price("VPS Starter", promo_code="LIMIT1")

	def test_promo_code_restriction(self):
		promo = frappe.get_doc({
			"doctype": "Hosting Promo Code",
			"code": "SHAREDONLY",
			"discount_type": "Percentage",
			"discount_value": 10.0,
			"product_group_restriction": "Shared Hosting"
		}).insert()

		with self.assertRaises(frappe.ValidationError):
			calculate_total_price("VPS Starter", promo_code="SHAREDONLY")
