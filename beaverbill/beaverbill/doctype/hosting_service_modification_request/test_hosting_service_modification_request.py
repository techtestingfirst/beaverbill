import frappe
import unittest
from frappe.utils import today, add_days, add_months

class TestHostingServiceModificationRequest(unittest.TestCase):
	def setUp(self):
		frappe.db.delete("Hosting Service Modification Request")
		frappe.db.delete("Hosting Subscription")
		frappe.db.delete("Hosting Product")
		frappe.db.delete("Customer Credit Transaction")
		frappe.db.delete("Hosting Invoice")

		# Hosting Subscription.customer links to User; create it so a
		# fresh site (CI) does not hit LinkValidationError.
		if not frappe.db.exists("User", "test_customer@beaver.com"):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": "test_customer@beaver.com",
					"first_name": "Beaver",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		# Ensure test products exist
		if not frappe.db.exists("Hosting Product Group", "VPS Servers"):
			frappe.get_doc({
				"doctype": "Hosting Product Group",
				"product_group_name": "VPS Servers"
			}).insert()

		self.vps_starter = frappe.get_doc({
			"doctype": "Hosting Product",
			"product_name": "VPS Starter",
			"product_group": "VPS Servers",
			"billing_cycle": "Monthly",
			"price": 10.0,
			"currency": "USD"
		}).insert()

		self.vps_pro = frappe.get_doc({
			"doctype": "Hosting Product",
			"product_name": "VPS Pro",
			"product_group": "VPS Servers",
			"billing_cycle": "Monthly",
			"price": 30.0,
			"currency": "USD"
		}).insert()

		# Create active subscription
		self.sub = frappe.get_doc({
			"doctype": "Hosting Subscription",
			"customer": "test_customer@beaver.com",
			"product": "VPS Starter",
			"status": "Active",
			"billing_cycle": "Monthly",
			"next_renewal_date": add_days(today(), 15), # Halfway through 30-day month
			"amount": 10.0,
			"currency": "USD"
		}).insert()

	def test_upgrade_proration_calculation(self):
		req = frappe.get_doc({
			"doctype": "Hosting Service Modification Request",
			"subscription": self.sub.name,
			"new_product": "VPS Pro"
		}).insert()

		# Halfway through: unused credit = 5.0, new cost = 15.0, net = 10.0
		self.assertAlmostEqual(float(req.proration_amount), 10.0, places=1)

		# Process upgrade
		req.process_modification()
		self.assertEqual(req.status, "Approved")
		self.assertTrue(req.invoice)

		# Simulate invoice payment
		inv = frappe.get_doc("Hosting Invoice", req.invoice)
		inv.status = "Paid"
		inv.save()

		# Apply change after payment
		req.apply_subscription_change()
		self.sub.reload()
		self.assertEqual(self.sub.product, "VPS Pro")
		self.assertEqual(float(self.sub.amount), 30.0)

	def test_downgrade_proration_calculation(self):
		# Change subscription to VPS Pro first
		self.sub.product = "VPS Pro"
		self.sub.amount = 30.0
		self.sub.save()

		req = frappe.get_doc({
			"doctype": "Hosting Service Modification Request",
			"subscription": self.sub.name,
			"new_product": "VPS Starter"
		}).insert()

		# Halfway through: unused credit = 15.0, new cost = 5.0, net = -10.0
		self.assertAlmostEqual(float(req.proration_amount), -10.0, places=1)

		# Process downgrade
		req.process_modification()
		self.assertEqual(req.status, "Completed")
		self.assertTrue(req.credit_transaction)

		# Verify subscription updated immediately
		self.sub.reload()
		self.assertEqual(self.sub.product, "VPS Starter")
		self.assertEqual(float(self.sub.amount), 10.0)
