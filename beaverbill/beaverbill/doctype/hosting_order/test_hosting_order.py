import frappe
import unittest
from frappe.utils import today, add_days
from beaverbill.beaverbill.doctype.hosting_subscription.hosting_subscription import process_subscription_renewals, get_customer_wallet_balance

class TestHostingOrder(unittest.TestCase):
	def setUp(self):
		frappe.db.delete("Hosting Subscription")
		frappe.db.delete("Hosting Invoice")
		frappe.db.delete("Hosting Order Item")
		frappe.db.delete("Hosting Order")
		frappe.db.delete("Customer Credit Transaction")

		# Ensure test user exists
		if not frappe.db.exists("User", "test_customer@beaver.com"):
			frappe.get_doc({
				"doctype": "User",
				"email": "test_customer@beaver.com",
				"first_name": "Test",
				"last_name": "Customer"
			}).insert()

		# Ensure test product exists
		if not frappe.db.exists("Hosting Product", "VPS Starter"):
			if not frappe.db.exists("Hosting Product Group", "VPS Servers"):
				frappe.get_doc({
					"doctype": "Hosting Product Group",
					"product_group_name": "VPS Servers"
				}).insert()

			frappe.get_doc({
				"doctype": "Hosting Product",
				"product_name": "VPS Starter",
				"product_group": "VPS Servers",
				"billing_cycle": "Monthly",
				"price": 10.0,
				"currency": "USD"
			}).insert()

	def test_checkout_and_payment_flow(self):
		order = frappe.get_doc({
			"doctype": "Hosting Order",
			"customer": "test_customer@beaver.com",
			"order_date": today(),
			"total_amount": 10.0,
			"currency": "USD",
			"items": [{
				"product": "VPS Starter",
				"qty": 1,
				"price": 10.0,
				"total": 10.0
			}]
		}).insert()

		self.assertEqual(order.status, "Pending")

		# Process payment
		order.process_payment()

		self.assertEqual(order.status, "Paid")

		# Verify Invoice was created and paid
		invoices = frappe.get_all("Hosting Invoice", filters={"order": order.name}, fields=["status", "total_amount"])
		self.assertEqual(len(invoices), 1)
		self.assertEqual(invoices[0].status, "Paid")
		self.assertEqual(float(invoices[0].total_amount), 10.0)

		# Verify Subscription was created
		subs = frappe.get_all("Hosting Subscription", filters={"order": order.name}, fields=["status", "product", "amount"])
		self.assertEqual(len(subs), 1)
		self.assertEqual(subs[0].status, "Active")
		self.assertEqual(subs[0].product, "VPS Starter")
		self.assertEqual(float(subs[0].amount), 10.0)

	def test_subscription_renewal_and_dunning(self):
		# Create a subscription that is due for renewal today
		sub = frappe.get_doc({
			"doctype": "Hosting Subscription",
			"customer": "test_customer@beaver.com",
			"product": "VPS Starter",
			"status": "Active",
			"billing_cycle": "Monthly",
			"next_renewal_date": today(),
			"amount": 10.0,
			"currency": "USD"
		}).insert()

		# Run renewals without wallet balance -> should suspend (dunning)
		process_subscription_renewals()

		sub.reload()
		self.assertEqual(sub.status, "Suspended")

		# Now add credit to wallet and reset subscription to Active and due today
		frappe.get_doc({
			"doctype": "Customer Credit Transaction",
			"customer": "test_customer@beaver.com",
			"transaction_date": today(),
			"amount": 20.0,
			"type": "Credit",
			"description": "Add funds"
		}).insert()

		self.assertEqual(get_customer_wallet_balance("test_customer@beaver.com"), 20.0)

		sub.status = "Active"
		sub.next_renewal_date = today()
		sub.save()

		# Run renewals with wallet balance -> should auto-charge and extend renewal date
		process_subscription_renewals()

		sub.reload()
		self.assertEqual(sub.status, "Active")
		self.assertNotEqual(sub.next_renewal_date, today())
		self.assertEqual(get_customer_wallet_balance("test_customer@beaver.com"), 10.0)
