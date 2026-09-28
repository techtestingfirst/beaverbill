import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from beaverbill.beaverbill.doctype.hosting_product.hosting_product import calculate_total_price
from beaverbill.beaverbill.pricing import calculate_price, convert, money, redeem_promo


def wipe():
	"""Test methods share one class-level transaction: clear Phase 2 fixtures first."""
	for dt, field, prefix in [
		("Hosting Product Price", "product", "Phase2 "),
		("Hosting Promo Redemption", "promo_code", "P2"),
		("Hosting Promo Code", "code", "P2"),
		("Hosting Tax Rule", "tax_name", "Phase2 "),
		("Hosting Customer Tax Profile", "user", ""),
		("Hosting Currency Exchange Rate", "from_currency", ""),
		("Hosting Product", "product_name", "Phase2 "),
		("Hosting Product Group", "product_group_name", "Phase2 "),
	]:
		for name in frappe.get_all(dt, pluck="name"):
			doc = frappe.get_doc(dt, name)
			value = str(doc.get(field) or "")
			if field == "user" and value != "Administrator":
				continue
			if field == "from_currency" and doc.get("effective_date") != today():
				continue
			if prefix and not value.startswith(prefix):
				continue
			frappe.delete_doc(dt, name, ignore_permissions=True, force=True)


def make_product(name="Phase2 VPS", group="Phase2 Group", price=100.0, cycle="Monthly"):
	if not frappe.db.exists("Hosting Product Group", group):
		frappe.get_doc({"doctype": "Hosting Product Group", "product_group_name": group}).insert()
	if not frappe.db.exists("Hosting Product", name):
		frappe.get_doc(
			{
				"doctype": "Hosting Product",
				"product_name": name,
				"product_group": group,
				"billing_cycle": cycle,
				"price": price,
				"currency": "USD",
			}
		).insert()
	return name


class TestCatalogPricing(IntegrationTestCase):
	def setUp(self):
		wipe()

	def test_legacy_fallback_without_versions(self):
		name = make_product("Phase2 Legacy", price=42.0)
		res = calculate_price(name)
		self.assertEqual(res["base_price"], 42.0)
		self.assertEqual(res["price_source"], "legacy")
		self.assertEqual(res["tax_total"], 0.0)

	def test_versioned_price_preferred_and_dated(self):
		name = make_product("Phase2 Versioned", price=100.0)
		frappe.get_doc(
			{
				"doctype": "Hosting Product Price",
				"product": name,
				"billing_cycle": "Monthly",
				"currency": "USD",
				"price": 80.0,
				"effective_from": add_days(today(), 1),
			}
		).insert()
		now = calculate_price(name)
		self.assertEqual(now["base_price"], 100.0)
		self.assertEqual(now["price_source"], "legacy")
		later = calculate_price(name, on_date=add_days(today(), 2))
		self.assertEqual(later["base_price"], 80.0)
		self.assertEqual(later["price_source"], "versioned")

	def test_tax_and_gst_split(self):
		name = make_product("Phase2 Taxed", price=100.0)
		frappe.get_doc(
			{
				"doctype": "Hosting Tax Rule",
				"tax_name": "Phase2 GST In-State",
				"country": "India",
				"state_code": "KA",
				"gst_mode": "CGST + SGST",
				"rate": 18,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Hosting Tax Rule",
				"tax_name": "Phase2 GST Out-State",
				"country": "India",
				"state_code": "KA",
				"gst_mode": "IGST",
				"rate": 18,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Hosting Customer Tax Profile",
				"user": "Administrator",
				"country": "India",
				"state": "KA",
			}
		).insert()
		try:
			res = calculate_price(name, customer="Administrator")
			parts = {line["part"]: line["amount"] for line in res["tax_breakdown"]}
			self.assertEqual(parts.get("CGST"), 9.0)
			self.assertEqual(parts.get("SGST"), 9.0)
			self.assertEqual(res["tax_total"], 18.0)
			self.assertEqual(res["total_price"], 118.0)
		finally:
			frappe.db.delete("Hosting Customer Tax Profile", {"user": "Administrator"})

	def test_igst_for_out_of_state(self):
		name = make_product("Phase2 IGST", price=200.0)
		frappe.get_doc(
			{
				"doctype": "Hosting Tax Rule",
				"tax_name": "Phase2 IGST In-State",
				"country": "India",
				"state_code": "KA",
				"gst_mode": "CGST + SGST",
				"rate": 18,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Hosting Tax Rule",
				"tax_name": "Phase2 IGST Out-State",
				"country": "India",
				"state_code": "KA",
				"gst_mode": "IGST",
				"rate": 18,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Hosting Customer Tax Profile",
				"user": "Administrator",
				"country": "India",
				"state": "MH",
			}
		).insert()
		try:
			res = calculate_price(name, customer="Administrator")
			parts = {line["part"]: line["amount"] for line in res["tax_breakdown"]}
			self.assertEqual(parts.get("IGST"), 36.0)
			self.assertNotIn("CGST", parts)
		finally:
			frappe.db.delete("Hosting Customer Tax Profile", {"user": "Administrator"})

	def test_tax_exempt_profile(self):
		name = make_product("Phase2 Exempt", price=100.0)
		frappe.get_doc(
			{
				"doctype": "Hosting Customer Tax Profile",
				"user": "Administrator",
				"country": "India",
				"state": "KA",
				"tax_exempt": 1,
			}
		).insert()
		try:
			res = calculate_price(name, customer="Administrator")
			self.assertEqual(res["tax_total"], 0.0)
			self.assertEqual(res["tax_breakdown"], [])
		finally:
			frappe.db.delete("Hosting Customer Tax Profile", {"user": "Administrator"})

	def test_fx_conversion_and_rounding(self):
		frappe.get_doc(
			{
				"doctype": "Hosting Currency Exchange Rate",
				"from_currency": "USD",
				"to_currency": "EUR",
				"rate": 0.9,
				"effective_date": today(),
			}
		).insert()
		self.assertEqual(convert(100.0, "USD", "EUR"), 90.0)
		self.assertEqual(convert(90.0, "EUR", "USD"), 100.0)
		self.assertEqual(convert(50.0, "USD", "USD"), 50.0)
		self.assertEqual(money(10.005, "USD"), 10.01)
		self.assertEqual(money(10.5, "JPY"), 11.0)
		name = make_product("Phase2 FX", price=100.0)
		res = calculate_price(name, target_currency="EUR")
		self.assertEqual(res["currency"], "EUR")
		self.assertEqual(res["base_price"], 90.0)

	def test_promo_order_restrictions(self):
		name = make_product("Phase2 Promo", price=100.0)
		for code, applies in [("P2FIRST", "First Order Only"), ("P2RENEW", "Renewals Only"), ("P2UP", "Upgrades Only")]:
			frappe.get_doc(
				{
					"doctype": "Hosting Promo Code",
					"code": code,
					"discount_type": "Fixed Amount",
					"discount_value": 10,
					"applies_to": applies,
				}
			).insert()
		self.assertRaises(
			frappe.ValidationError, calculate_total_price, name, promo_code="P2FIRST"
		)
		res = calculate_total_price(name, promo_code="P2FIRST", order_context={"is_first_order": True})
		self.assertEqual(res["total_price"], 90.0)
		self.assertRaises(
			frappe.ValidationError,
			calculate_total_price,
			name,
			promo_code="P2RENEW",
			order_context={"is_first_order": True},
		)
		res = calculate_total_price(name, promo_code="P2RENEW", order_context={"is_renewal": True})
		self.assertEqual(res["total_price"], 90.0)
		res = calculate_total_price(name, promo_code="P2UP", order_context={"is_upgrade": True})
		self.assertEqual(res["total_price"], 90.0)

	def test_concurrency_safe_redemption(self):
		name = make_product("Phase2 Race", price=100.0)
		frappe.get_doc(
			{
				"doctype": "Hosting Promo Code",
				"code": "P2ONCE",
				"discount_type": "Fixed Amount",
				"discount_value": 5,
				"usage_limit": 1,
			}
		).insert()
		first = redeem_promo("P2ONCE", product_name=name, discount_given=5)
		self.assertTrue(first)
		self.assertRaises(frappe.ValidationError, redeem_promo, "P2ONCE", name)
		promo = frappe.get_doc("Hosting Promo Code", "P2ONCE")
		self.assertEqual(promo.used_count, 1)
		self.assertEqual(frappe.db.count("Hosting Promo Redemption", {"promo_code": "P2ONCE"}), 1)

	def test_snapshot_contents(self):
		name = make_product("Phase2 Snap", price=100.0)
		frappe.get_doc(
			{
				"doctype": "Hosting Promo Code",
				"code": "P2SNAP10",
				"discount_type": "Percentage",
				"discount_value": 10,
			}
		).insert()
		res = calculate_price(name, promo_code="P2SNAP10")
		snap = json.loads(res["snapshot"])
		self.assertEqual(snap["base_price"], 100.0)
		self.assertEqual(snap["discount"], 10.0)
		self.assertEqual(snap["subtotal"], 90.0)
		self.assertEqual(snap["lines"][0]["kind"], "base")

	def test_order_item_and_invoice_snapshot_fields(self):
		name = make_product("Phase2 Fields", price=100.0)
		res = calculate_price(name)
		item = frappe.get_doc(
			{
				"doctype": "Hosting Order Item",
				"product": name,
				"qty": 1,
				"price": res["base_price"],
				"total": res["subtotal"],
				"base_price": res["base_price"],
				"discount_amount": res["discount"],
				"billing_cycle": res["billing_cycle"],
				"calculation_snapshot": res["snapshot"],
			}
		)
		self.assertEqual(item.base_price, 100.0)
		self.assertEqual(json.loads(item.calculation_snapshot)["currency"], "USD")
		invoice = frappe.get_doc(
			{
				"doctype": "Hosting Invoice",
				"customer": "Administrator",
				"invoice_date": today(),
				"due_date": today(),
				"status": "Unpaid",
				"subtotal": res["subtotal"],
				"discount_amount": res["discount"],
				"tax_amount": res["tax_total"],
				"total_amount": res["total_price"],
				"currency": "USD",
				"pricing_snapshot": res["snapshot"],
			}
		)
		self.assertEqual(invoice.total_amount, 100.0)

	def test_phase2_patch_idempotent(self):
		from beaverbill.patches.phase2_seed_product_prices import execute

		execute()
		execute()
