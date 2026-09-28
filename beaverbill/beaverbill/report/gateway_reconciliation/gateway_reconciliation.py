import frappe

from beaverbill.beaverbill.gateways import reconcile_gateway


def execute(filters=None):
	columns = [
		{"label": "Area", "fieldname": "area", "fieldtype": "Data", "width": 160},
		{"label": "Reference", "fieldname": "reference", "fieldtype": "Data", "width": 200},
		{"label": "Detail", "fieldname": "detail", "fieldtype": "Data", "width": 300},
	]
	data = []
	gateways = filters.get("gateway") if filters else None
	names = [gateways] if gateways else frappe.get_all("Hosting Payment Gateway", pluck="name")
	for name in names:
		report = reconcile_gateway(name)
		for ref in report["stuck_payments"]:
			data.append({"area": "Stuck payment", "reference": ref, "detail": f"No processed event on {name}"})
		for ref in report["orphan_events"]:
			data.append({"area": "Orphan event", "reference": ref, "detail": f"No payment linked on {name}"})
		for row in report["amount_mismatches"]:
			data.append(
				{
					"area": "Amount mismatch",
					"reference": row["payment"],
					"detail": f"Local {row['local']} vs event {row['remote']}",
				}
			)
	return columns, data
