import frappe


def execute(filters=None):
	columns = [
		{"label": "Event", "fieldname": "name", "fieldtype": "Link", "options": "Hosting Payment Event", "width": 160},
		{"label": "Gateway", "fieldname": "gateway", "fieldtype": "Link", "options": "Hosting Payment Gateway", "width": 160},
		{"label": "Type", "fieldname": "event_type", "fieldtype": "Data", "width": 200},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 110},
		{"label": "Attempts", "fieldname": "attempts", "fieldtype": "Int", "width": 90},
		{"label": "Last Error", "fieldname": "last_error", "fieldtype": "Data", "width": 300},
	]
	data = frappe.get_all(
		"Hosting Payment Event",
		filters={"status": ["in", ["Received", "Validated", "Failed"]]},
		fields=["name", "gateway", "event_type", "status", "attempts", "last_error"],
		order_by="modified desc",
	)
	return columns, data
