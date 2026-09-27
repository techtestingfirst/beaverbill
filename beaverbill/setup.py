import frappe


def after_install():
	create_roles()


def create_roles():
	roles = [
		{"role_name": "Hosting Customer", "desk_access": 0},
		{"role_name": "Hosting Support", "desk_access": 1},
		{"role_name": "Hosting Admin", "desk_access": 1},
	]

	for role_data in roles:
		if not frappe.db.exists("Role", role_data["role_name"]):
			frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role_data["role_name"],
					"desk_access": role_data["desk_access"],
				}
			).insert(ignore_permissions=True)
