import frappe

from beaverbill.beaverbill.billing import ledger_mismatches


def execute(filters=None):
	columns = [
		{"label": "Entry", "fieldname": "name", "fieldtype": "Link", "options": "Customer Credit Transaction", "width": 200},
		{"label": "Issue", "fieldname": "issue", "fieldtype": "Data", "width": 300},
	]
	names = ledger_mismatches()
	data = [{"name": name, "issue": "balance_after differs from running sum"} for name in names]
	return columns, data
