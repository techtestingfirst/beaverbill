import frappe
from frappe.tests import IntegrationTestCase

from beaverbill.beaverbill.backfill_services import execute_backfill, preview_backfill
from beaverbill.beaverbill.pricing import calculate_price


def wipe():
	for dt in [
		"Hosting Service",
		"Hosting Customer Contact",
		"Hosting Customer",
		"Hosting Customer Group",
		"Hosting Subscription",
		"Hosting Order",
	]:
		for name in frappe.get_all(dt, pluck="name"):
			frappe.delete_doc(dt, name, ignore_permissions=True, force=True)


def make_user(email, roles):
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	user.roles = []
	for role in roles:
		user.append("roles", {"role": role})
	user.save(ignore_permissions=True)
	return user.name


def ensure_probe_product():
	if not frappe.db.exists("Hosting Product Group", "Phase3 Group"):
		frappe.get_doc({"doctype": "Hosting Product Group", "product_group_name": "Phase3 Group"}).insert()
	if not frappe.db.exists("Hosting Product", "VPS Probe"):
		frappe.get_doc(
			{
				"doctype": "Hosting Product",
				"product_name": "VPS Probe",
				"product_group": "Phase3 Group",
				"billing_cycle": "Monthly",
				"price": 10,
				"currency": "USD",
			}
		).insert()


def make_customer(name, user=None, customer_type="Individual", **kwargs):
	doc = frappe.get_doc(
		{
			"doctype": "Hosting Customer",
			"customer_name": name,
			"customer_type": customer_type,
			"primary_user": user,
			"status": "Active",
			**kwargs,
		}
	)
	doc.insert()
	return doc.name


class TestCustomerService(IntegrationTestCase):
	def setUp(self):
		wipe()
		frappe.set_user("Administrator")

	def test_company_requires_company_name(self):
		doc = frappe.get_doc(
			{"doctype": "Hosting Customer", "customer_name": "Acme?", "customer_type": "Company", "status": "Active"}
		)
		self.assertRaises(frappe.ValidationError, doc.insert)
		doc.company_name = "Acme Inc"
		doc.insert()
		self.assertEqual(doc.customer_name, "Acme?")

	def test_consent_timestamp_set(self):
		name = make_customer("Consent Guy", customer_type="Individual")
		doc = frappe.get_doc("Hosting Customer", name)
		doc.consent_terms = 1
		doc.save()
		self.assertIsNotNone(doc.consent_datetime)

	def test_contacts_crud_and_email_validation(self):
		customer = make_customer("Contact Owner")
		contact = frappe.get_doc(
			{
				"doctype": "Hosting Customer Contact",
				"customer": customer,
				"contact_type": "Billing",
				"full_name": "Bill Payer",
				"email": "bill@example.com",
			}
		).insert()
		self.assertEqual(contact.contact_type, "Billing")
		bad = frappe.get_doc(
			{
				"doctype": "Hosting Customer Contact",
				"customer": customer,
				"contact_type": "Technical",
				"full_name": "Bad Email",
				"email": "not-an-email",
			}
		)
		self.assertRaises(frappe.ValidationError, bad.insert)

	def test_service_lifecycle_and_timestamps(self):
		customer = make_customer("Lifecycle Co", customer_type="Company", company_name="Lifecycle Co")
		service = frappe.get_doc({"doctype": "Hosting Service", "customer": customer}).insert()
		self.assertEqual(service.status, "Pending")
		service.status = "Active"
		self.assertRaises(frappe.ValidationError, service.save)
		service.reload()
		service.status = "Provisioning"
		service.save()
		self.assertIsNotNone(service.provisioned_at)
		service.status = "Active"
		service.save()
		service.status = "Suspended"
		service.save()
		self.assertIsNotNone(service.suspended_at)
		service.status = "Archived"
		self.assertRaises(frappe.ValidationError, service.save)

	def test_service_ownership(self):
		owner = make_user("phase3-owner@example.com", ["Hosting Customer"])
		other = make_user("phase3-other@example.com", ["Hosting Customer"])
		staff = make_user("phase3-staff@example.com", ["Hosting Support"])
		mine = make_customer("Mine", user=owner)
		theirs = make_customer("Theirs", user=other)
		my_service = frappe.get_doc({"doctype": "Hosting Service", "customer": mine}).insert()
		their_service = frappe.get_doc({"doctype": "Hosting Service", "customer": theirs}).insert()
		try:
			self.assertTrue(frappe.has_permission("Hosting Service", "read", doc=my_service.name, user=owner))
			self.assertFalse(frappe.has_permission("Hosting Service", "read", doc=their_service.name, user=owner))
			self.assertFalse(frappe.has_permission("Hosting Service", "write", doc=my_service.name, user=owner))
			self.assertTrue(frappe.has_permission("Hosting Service", "read", doc=my_service.name, user=staff))
			frappe.set_user(owner)
			try:
				mine_doc = frappe.get_doc("Hosting Service", my_service.name)
				mine_doc.check_permission("read")
				self.assertEqual(mine_doc.customer, mine)
				theirs_doc = frappe.get_doc("Hosting Service", their_service.name)
				self.assertRaises(frappe.PermissionError, theirs_doc.check_permission, "read")
				visible = frappe.get_list("Hosting Service", fields=["name"])
				self.assertEqual({row.name for row in visible}, {my_service.name})
			finally:
				frappe.set_user("Administrator")
		finally:
			frappe.delete_doc("Hosting Service", my_service.name, ignore_permissions=True, force=True)
			frappe.delete_doc("Hosting Service", their_service.name, ignore_permissions=True, force=True)

	def test_backfill_preview_execute_idempotent(self):
		user = make_user("phase3-buyer@example.com", ["Hosting Customer"])
		customer = make_customer("Buyer", user=user)
		ensure_probe_product()
		order = frappe.get_doc(
			{
				"doctype": "Hosting Order",
				"customer": user,
				"order_date": frappe.utils.today(),
				"status": "Paid",
				"currency": "USD",
				"total_amount": 10,
				"items": [{"product": "VPS Probe", "qty": 1, "price": 10, "total": 10}],
			}
		)
		order.insert()
		sub = frappe.get_doc(
			{
				"doctype": "Hosting Subscription",
				"customer": user,
				"product": "VPS Probe",
				"status": "Active",
				"billing_cycle": "Monthly",
				"next_renewal_date": frappe.utils.add_days(frappe.utils.today(), 30),
				"amount": 10,
				"currency": "USD",
				"order": order.name,
			}
		).insert()
		preview = preview_backfill()
		self.assertEqual(preview["would_create"], 1)
		first = execute_backfill(dry_run=False)
		self.assertEqual(len(first["created"]), 1)
		service = frappe.get_doc("Hosting Service", first["created"][0])
		self.assertEqual(service.customer, customer)
		self.assertEqual(service.subscription, sub.name)
		second = execute_backfill(dry_run=False)
		self.assertEqual(len(second["created"]), 0)
		self.assertEqual(second["duplicates"], 1)

	def test_backfill_orphan_and_missing_customer(self):
		ensure_probe_product()
		ghost = make_user("phase3-ghost@example.com", ["Hosting Customer"])
		sub = frappe.get_doc(
			{
				"doctype": "Hosting Subscription",
				"customer": ghost,
				"product": "VPS Probe",
				"status": "Active",
				"billing_cycle": "Monthly",
				"next_renewal_date": frappe.utils.add_days(frappe.utils.today(), 30),
				"amount": 10,
				"currency": "USD",
			}
		).insert()
		report = preview_backfill()
		self.assertEqual(report["would_create"], 0)
		self.assertEqual(report["orphans"], 1)

	def test_tax_profile_via_customer_link(self):
		if not frappe.db.exists("Hosting Product", "Phase3 Taxed"):
			if not frappe.db.exists("Hosting Product Group", "Phase3 Group"):
				frappe.get_doc(
					{"doctype": "Hosting Product Group", "product_group_name": "Phase3 Group"}
				).insert()
			frappe.get_doc(
				{
					"doctype": "Hosting Product",
					"product_name": "Phase3 Taxed",
					"product_group": "Phase3 Group",
					"billing_cycle": "Monthly",
					"price": 100,
					"currency": "USD",
				}
			).insert()
		frappe.get_doc(
			{
				"doctype": "Hosting Tax Rule",
				"tax_name": "Phase3 VAT",
				"rate": 10,
			}
		).insert()
		customer = make_customer("Taxed Buyer")
		frappe.get_doc(
			{"doctype": "Hosting Customer Tax Profile", "user": "Administrator", "customer": customer}
		).insert()
		res = calculate_price("Phase3 Taxed", customer=customer)
		self.assertEqual(res["tax_total"], 10.0)
