import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate, date_diff, add_months

class HostingServiceModificationRequest(Document):
	def validate(self):
		if self.status == "Pending":
			self.calculate_proration()

	def calculate_proration(self):
		sub = frappe.get_doc("Hosting Subscription", self.subscription)
		new_prod = frappe.get_doc("Hosting Product", self.new_product)

		# Calculate remaining days in current cycle
		renewal_date = getdate(sub.next_renewal_date)
		current_date = getdate(today())

		if renewal_date <= current_date:
			# Already due or past due, no proration credit
			self.proration_amount = float(new_prod.price)
			return

		# Determine total days in current cycle
		months_to_subtract = 1
		if sub.billing_cycle == "Quarterly":
			months_to_subtract = 3
		elif sub.billing_cycle == "Semi-Annually":
			months_to_subtract = 6
		elif sub.billing_cycle == "Annually":
			months_to_subtract = 12

		start_date = add_months(renewal_date, -months_to_subtract)
		total_days = date_diff(renewal_date, start_date) or 30
		remaining_days = date_diff(renewal_date, current_date)

		ratio = float(remaining_days) / float(total_days)

		unused_credit = float(sub.amount) * ratio
		new_cost = float(new_prod.price) * ratio

		self.proration_amount = round(new_cost - unused_credit, 2)

	def process_modification(self):
		"""
		Applies the upgrade/downgrade.
		If proration_amount > 0, creates an invoice.
		If proration_amount <= 0, creates a credit note and immediately completes.
		"""
		if self.status != "Pending":
			return

		sub = frappe.get_doc("Hosting Subscription", self.subscription)

		if self.proration_amount > 0:
			# Upgrade: Create Invoice
			invoice = frappe.get_doc({
				"doctype": "Hosting Invoice",
				"customer": sub.customer,
				"invoice_date": today(),
				"due_date": today(),
				"status": "Unpaid",
				"total_amount": self.proration_amount,
				"currency": sub.currency
			}).insert()
			self.invoice = invoice.name
			self.status = "Approved"
		else:
			# Downgrade: Create Credit Note (Customer Credit Transaction)
			credit_amount = abs(self.proration_amount)
			if credit_amount > 0:
				credit_tx = frappe.get_doc({
					"doctype": "Customer Credit Transaction",
					"customer": sub.customer,
					"transaction_date": today(),
					"amount": credit_amount,
					"type": "Credit",
					"description": f"Prorated credit for downgrade of subscription {sub.name}"
				}).insert()
				self.credit_transaction = credit_tx.name

			# Apply changes immediately
			self.apply_subscription_change()
			self.status = "Completed"

		self.save()

	def apply_subscription_change(self):
		sub = frappe.get_doc("Hosting Subscription", self.subscription)
		new_prod = frappe.get_doc("Hosting Product", self.new_product)
		sub.product = self.new_product
		sub.amount = new_prod.price
		sub.billing_cycle = new_prod.billing_cycle
		sub.save()

		# Trigger simulated provisioning hook
		self.trigger_provisioning_resize(sub)

	def trigger_provisioning_resize(self, subscription):
		# Simulated provisioning hook
		frappe.logger().info(f"Provisioning: Resized subscription {subscription.name} to product {subscription.product}")
