import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate, add_months

class HostingSubscription(Document):
	pass

def process_subscription_renewals():
	"""
	Daily scheduler task to check for subscriptions due for renewal,
	generate renewal invoices, and handle dunning/suspension.
	"""
	today_date = getdate(today())
	active_subs = frappe.get_all("Hosting Subscription", filters={"status": "Active"}, fields=["name", "customer", "product", "billing_cycle", "amount", "currency", "next_renewal_date"])

	for sub in active_subs:
		renewal_date = getdate(sub.next_renewal_date)
		if renewal_date <= today_date:
			# Generate renewal invoice
			invoice = frappe.get_doc({
				"doctype": "Hosting Invoice",
				"customer": sub.customer,
				"invoice_date": today(),
				"due_date": today(),
				"status": "Unpaid",
				"total_amount": sub.amount,
				"currency": sub.currency
			}).insert()

			# Attempt auto-charge from customer credit/wallet
			wallet_balance = get_customer_wallet_balance(sub.customer)
			if wallet_balance >= float(sub.amount):
				# Deduct from wallet
				frappe.get_doc({
					"doctype": "Customer Credit Transaction",
					"customer": sub.customer,
					"transaction_date": today(),
					"amount": -float(sub.amount),
					"type": "Debit",
					"description": f"Auto-renewal payment for subscription {sub.name}"
				}).insert()

				invoice.status = "Paid"
				invoice.save()

				# Update subscription renewal date
				months_to_add = 1
				if sub.billing_cycle == "Quarterly":
					months_to_add = 3
				elif sub.billing_cycle == "Semi-Annually":
					months_to_add = 6
				elif sub.billing_cycle == "Annually":
					months_to_add = 12

				sub_doc = frappe.get_doc("Hosting Subscription", sub.name)
				sub_doc.next_renewal_date = add_months(sub.next_renewal_date, months_to_add)
				sub_doc.save()
			else:
				# Dunning: If unpaid and past due, suspend subscription
				sub_doc = frappe.get_doc("Hosting Subscription", sub.name)
				sub_doc.status = "Suspended"
				sub_doc.save()

def get_customer_wallet_balance(customer):
	txs = frappe.get_all("Customer Credit Transaction", filters={"customer": customer}, fields=["amount"])
	return sum(float(tx.amount) for tx in txs)
