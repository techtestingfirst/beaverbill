import frappe


def execute(filters=None):
	columns = [
		{"label": "IP Address", "fieldname": "ip_address", "fieldtype": "Link", "options": "IPAM IP Address", "width": 150},
		{"label": "Finding", "fieldname": "finding", "fieldtype": "Data", "width": 300},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 110},
		{"label": "Allocated To", "fieldname": "allocated_to", "fieldtype": "Data", "width": 200},
	]
	data = []
	for ip in frappe.get_all(
		"IPAM IP Address",
		filters={"status": "Allocated"},
		fields=["name", "status", "allocated_to_doctype", "allocated_to_name"],
	):
		if not ip.allocated_to_name:
			data.append(
				{
					"ip_address": ip.name,
					"finding": "Allocated without a reference (orphaned allocation)",
					"status": ip.status,
					"allocated_to": "",
				}
			)
	allocations = frappe.db.get_all(
		"IPAM Allocation Log",
		filters={"action": "Allocated"},
		fields=["ip_address", {"COUNT": "name", "as": "allocates"}, {"MAX": "creation", "as": "last_allocate"}],
		group_by="ip_address",
	)
	for row in allocations:
		releases = frappe.db.count(
			"IPAM Allocation Log",
			{"ip_address": row.ip_address, "action": "Released", "creation": [">", row.last_allocate]},
		)
		current = frappe.db.get_value("IPAM IP Address", row.ip_address, "status")
		if current == "Allocated" and row.allocates > 1 and releases == 0:
			# More than one allocate logged and none released since: possible double allocation.
			prior = frappe.db.get_all(
				"IPAM Allocation Log",
				filters={"ip_address": row.ip_address, "action": "Allocated"},
				fields=["reference_doctype", "reference_name"],
				order_by="creation asc",
				limit=2,
			)
			refs = {f"{p.reference_doctype}:{p.reference_name}" for p in prior}
			if len(refs) > 1:
				data.append(
					{
						"ip_address": row.ip_address,
						"finding": f"Allocated {row.allocates}x to different references without release",
						"status": current,
						"allocated_to": ", ".join(sorted(refs)),
					}
				)
	return columns, data
