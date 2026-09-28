import frappe


def execute(filters=None):
	columns = [
		{"label": "Subnet", "fieldname": "subnet", "fieldtype": "Link", "options": "IPAM Subnet", "width": 180},
		{"label": "CIDR", "fieldname": "cidr", "fieldtype": "Data", "width": 140},
		{"label": "Total IPs", "fieldname": "total", "fieldtype": "Int", "width": 90},
		{"label": "Available", "fieldname": "available", "fieldtype": "Int", "width": 90},
		{"label": "Used %", "fieldname": "used_pct", "fieldtype": "Percent", "width": 90},
		{"label": "Pool Status", "fieldname": "pool_status", "fieldtype": "Data", "width": 110},
	]
	data = []
	subnets = frappe.get_all("IPAM Subnet", fields=["name", "cidr"])
	for subnet in subnets:
		counts = frappe.db.get_all(
			"IPAM IP Address",
			filters={"subnet": subnet.name},
			fields=["status", {"COUNT": "name", "as": "total"}],
			group_by="status",
			as_list=False,
		)
		by_status = {row.status: row.total for row in counts}
		total = sum(by_status.values())
		available = by_status.get("Available", 0)
		used_pct = round(100 * (total - available) / total, 1) if total else 0
		if total == 0 or available == 0:
			pool_status = "Exhausted"
		elif available / total < 0.1:
			pool_status = "Low"
		else:
			pool_status = "OK"
		data.append(
			{
				"subnet": subnet.name,
				"cidr": subnet.cidr,
				"total": total,
				"available": available,
				"used_pct": used_pct,
				"pool_status": pool_status,
			}
		)
	return columns, data
