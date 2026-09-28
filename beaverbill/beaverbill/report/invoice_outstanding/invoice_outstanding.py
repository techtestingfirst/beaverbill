import frappe

from beaverbill.beaverbill.billing import outstanding_invoices


def execute(filters=None):
	columns = [
		{"label": "Invoice", "fieldname": "name", "fieldtype": "Link", "options": "Hosting Invoice", "width": 140},
		{"label": "Customer", "fieldname": "customer", "fieldtype": "Link", "options": "User", "width": 180},
		{"label": "Total", "fieldname": "total_amount", "fieldtype": "Currency", "width": 110},
		{"label": "Paid", "fieldname": "paid_amount", "fieldtype": "Currency", "width": 110},
		{"label": "Outstanding", "fieldname": "outstanding", "fieldtype": "Currency", "width": 120},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 110},
		{"label": "Due Date", "fieldname": "due_date", "fieldtype": "Date", "width": 110},
	]
	return columns, outstanding_invoices()
