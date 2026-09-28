"""Phase 3 backfill: draft Hosting Service records from live subscriptions/orders.

Duplicate-safe: a service is never created twice for the same subscription
or order item. Missing customers and orphan subscriptions are reported,
never guessed. Run preview_backfill() first; execute_backfill() writes
only when dry_run=False.
"""

import frappe


def customer_for_user(user):
	return frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")


def service_exists(subscription=None, order=None, order_item=None):
	filters = {}
	if subscription:
		filters["subscription"] = subscription
	if order:
		filters["order"] = order
	if order_item:
		filters["order_item"] = order_item
	return frappe.db.exists("Hosting Service", filters) if filters else None


def collect_candidates():
	"""Rows that should become services, plus problem rows."""
	planned, duplicates, orphans, missing_customers = [], [], [], []
	covered_orders = set()
	for sub in frappe.get_all(
		"Hosting Subscription",
		filters={"status": "Active"},
		fields=["name", "customer", "product", "billing_cycle", "order", "currency"],
	):
		if sub.order:
			covered_orders.add((sub.order, sub.product))
		if service_exists(subscription=sub.name):
			duplicates.append({"subscription": sub.name, "reason": "service already exists"})
			continue
		customer, source = None, ""
		if sub.order:
			order_customer = frappe.db.get_value("Hosting Order", sub.order, "customer")
			customer = customer_for_user(order_customer) if order_customer else None
			source = f"order {sub.order}"
		if not customer and sub.customer:
			customer = customer_for_user(sub.customer)
			source = source or f"subscription user {sub.customer}"
		if not customer:
			orphans.append({"subscription": sub.name, "reason": f"no customer record ({source or 'no order'})"})
			continue
		planned.append(
			{
				"customer": customer,
				"product": sub.product,
				"billing_cycle": sub.billing_cycle,
				"order": sub.order or "",
				"order_item": "",
				"subscription": sub.name,
			}
		)
	for order in frappe.get_all("Hosting Order", filters={"status": ["!=", "Cancelled"]}, fields=["name", "customer"]):
		doc = frappe.get_doc("Hosting Order", order.name)
		for item in doc.items:
			if (order.name, item.product) in covered_orders:
				continue
			if service_exists(order=order.name, order_item=item.name):
				duplicates.append(
					{"order": order.name, "order_item": item.name, "reason": "service already exists"}
				)
				continue
			customer = customer_for_user(order.customer) if order.customer else None
			if not customer:
				missing_customers.append(
					{"order": order.name, "order_item": item.name, "reason": "no customer record for order user"}
				)
				continue
			planned.append(
				{
					"customer": customer,
					"product": item.product,
					"billing_cycle": "",
					"order": order.name,
					"order_item": item.name,
					"subscription": "",
				}
			)
	return {
		"planned": planned,
		"duplicates": duplicates,
		"orphans": orphans,
		"missing_customers": missing_customers,
	}


def preview_backfill():
	report = collect_candidates()
	return {
		"would_create": len(report["planned"]),
		"duplicates": len(report["duplicates"]),
		"orphans": len(report["orphans"]),
		"missing_customers": len(report["missing_customers"]),
		"details": report,
	}


def execute_backfill(dry_run=True):
	report = collect_candidates()
	created = []
	if not dry_run:
		for row in report["planned"]:
			doc = frappe.get_doc({"doctype": "Hosting Service", "status": "Pending", **row})
			doc.insert(ignore_permissions=True)
			created.append(doc.name)
	return {
		"dry_run": dry_run,
		"created": created,
		"would_create": len(report["planned"]),
		"duplicates": len(report["duplicates"]),
		"orphans": len(report["orphans"]),
		"missing_customers": len(report["missing_customers"]),
		"details": report,
	}
