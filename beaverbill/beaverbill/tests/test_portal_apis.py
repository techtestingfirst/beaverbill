"""Phase 10 tests: portal auth, ownership, commerce, services, assets, tickets."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from beaverbill.beaverbill import billing as ledger
from beaverbill.beaverbill.portal import account, assets, billing, catalog, guard, orders, services, support


def wipe():
	from beaverbill.beaverbill import addons as _ao
	from beaverbill.beaverbill import backups as _bk
	from beaverbill.beaverbill import certificates as _ct
	from beaverbill.beaverbill.domains import REGISTRAR_FAULTS, SimulatedRegistrarDriver
	from beaverbill.beaverbill import domains as _dm

	for dt in [
		"Portal Audit Event",
		"Customer Notification",
		"Service Action",
		"HD Ticket Comment",
		"HD Ticket",
		"Restore Request",
		"Service Backup",
		"Backup Policy",
		"Service Addon",
		"Service Storage Usage",
		"SSL Certificate",
		"Hosting DNS Record",
		"Hosting Domain",
		"Domain Registrar Account",
		"Hosting Service Modification Request",
		"Hosting Modification Event",
		"Hosting Subscription",
		"Hosting Payment Allocation",
		"Hosting Payment Transaction",
		"Hosting Payment Method",
		"Hosting Payment Gateway",
		"Hosting Promo Redemption",
		"Hosting Promo Code",
		"Hosting Invoice Item",
		"Hosting Invoice",
		"Hosting Order Item",
		"Hosting Order",
		"Provisioning Attempt",
		"Provisioning Operation",
		"Provider Request Log",
		"Hosting Customer Contact",
		"Hosting Service",
		"Hosting Product Addon",
		"Hosting Configurable Option",
		"Hosting Product",
		"Hosting Provider Account",
		"Hosting Customer",
	]:
		try:
			for name in frappe.get_all(dt, pluck="name"):
				frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
		except Exception:
			continue
	frappe.cache().delete_value(f"portal-cart:phase10a@example.com")
	frappe.cache().delete_value(f"portal-cart:phase10b@example.com")
	SimulatedRegistrarDriver.REGISTRY.clear()
	REGISTRAR_FAULTS.clear()
	_ct.CERT_FAULTS.clear()
	_bk.BACKUP_FAULTS.clear()
	_ao.ADDON_FAULTS.clear()
	_dm.REGISTRAR_FAULTS.clear()
	frappe.db.commit()


def grant_customer_role(email):
	user = frappe.get_doc("User", email)
	user.add_roles("Hosting Customer")


def ensure_user(email, first="Phase10"):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": first, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return email


def ensure_customer(user, name="Buyer"):
	existing = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
	if existing:
		return existing
	return frappe.get_doc(
		{"doctype": "Hosting Customer", "customer_name": name,
		 "primary_user": user, "status": "Active"}
	).insert().name


def ensure_product(name="Phase10 Small", price=10, group="Phase10 Group"):
	if not frappe.db.exists("Hosting Product Group", group):
		frappe.get_doc({"doctype": "Hosting Product Group", "product_group_name": group}).insert()
	if frappe.db.exists("Hosting Product", name):
		return name
	return frappe.get_doc(
		{
			"doctype": "Hosting Product",
			"product_name": name,
			"product_group": group,
			"billing_cycle": "Monthly",
			"price": price,
			"currency": "USD",
		}
	).insert().name


def ensure_status():
	if not frappe.get_all("HD Ticket Status", limit=1):
		frappe.get_doc(
			{"doctype": "HD Ticket Status", "label_agent": "Open",
			 "label_customer": "Open", "category": "Open"}
		).insert(ignore_permissions=True)


class TestPortalAuth(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.user_a = ensure_user("phase10a@example.com")
		self.user_b = ensure_user("phase10b@example.com")
		self.plain = ensure_user("phase10plain@example.com", "Plain")
		self.customer_a = ensure_customer(self.user_a, "A Buyer")
		self.customer_b = ensure_customer(self.user_b, "B Buyer")
		grant_customer_role(self.user_a)
		grant_customer_role(self.user_b)

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_guest_denied(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			account.get_profile.__wrapped__()

	def test_user_without_customer_denied(self):
		frappe.set_user(self.plain)
		with self.assertRaises(frappe.PermissionError):
			account.get_profile.__wrapped__()

	def test_session_status(self):
		frappe.set_user(self.user_a)
		out = services.service_dashboard.__wrapped__() if False else None
		status = account.session_status.__wrapped__()
		self.assertEqual(status["user"], self.user_a)
		self.assertEqual(status["customer"], self.customer_a)

	def test_cross_customer_reads_denied(self):
		frappe.set_user("Administrator")
		product = ensure_product()
		svc_b = frappe.get_doc(
			{"doctype": "Hosting Service", "customer": self.customer_b,
			 "status": "Pending", "product": product, "billing_cycle": "Monthly"}
		).insert()
		inv_b = ledger.issue_invoice(
			self.user_b, [{"description": "B line", "qty": 1, "unit_price": 5, "line_total": 5}],
			currency="USD", idempotency_key="phase10-b-inv")
		frappe.set_user(self.user_b)
		_ = out = None
		frappe.set_user(self.user_a)
		with self.assertRaises(frappe.PermissionError):
			services.service_detail.__wrapped__(svc_b.name)
		with self.assertRaises(frappe.PermissionError):
			billing.get_invoice.__wrapped__(inv_b.name)
		with self.assertRaises(frappe.DoesNotExistError):
			services.service_detail.__wrapped__("no-such-service")

	def test_rate_limit_trips(self):
		frappe.set_user(self.user_a)
		guard.check_rate("phase10-probe", 1000)
		guard.check_rate("phase10-tight", 2, window=60)
		guard.check_rate("phase10-tight", 2, window=60)
		with self.assertRaises(frappe.RateLimitExceededError):
			guard.check_rate("phase10-tight", 2, window=60)

	def test_audit_events_recorded(self):
		frappe.set_user(self.user_a)
		account.get_profile()
		rows = frappe.get_all("Portal Audit Event",
							  filters={"endpoint": "portal.get_profile", "user": self.user_a})
		self.assertTrue(rows)
		with self.assertRaises(frappe.DoesNotExistError):
			services.service_detail("no-such-service")
		denied = frappe.get_all("Portal Audit Event",
								filters={"endpoint": "portal.service_detail", "status": "Error"})
		self.assertTrue(denied)


class TestPortalCommerce(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.user_a = ensure_user("phase10a@example.com")
		self.customer_a = ensure_customer(self.user_a, "A Buyer")
		grant_customer_role(self.user_a)
		self.product = ensure_product()
		frappe.set_user(self.user_a)

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_profile_and_contacts(self):
		prof = account.get_profile.__wrapped__()
		self.assertEqual(prof["name"], self.customer_a)
		updated = account.update_profile.__wrapped__(customer_name="A Renamed", locale="en-IN")
		self.assertEqual(updated["customer_name"], "A Renamed")
		added = account.add_contact.__wrapped__("Billing", "A Acct", "acct@example.com")
		listed = account.list_contacts.__wrapped__()
		self.assertEqual(len(listed["contacts"]), 1)
		account.update_contact.__wrapped__(added["contact"], phone="+91-1")
		account.delete_contact.__wrapped__(added["contact"])
		self.assertEqual(account.list_contacts.__wrapped__()["contacts"], [])

	def test_catalog_and_coupon(self):
		items = catalog.list_products.__wrapped__()
		self.assertTrue([p for p in items["products"] if p["name"] == self.product])
		detail = catalog.get_product.__wrapped__(self.product)
		self.assertEqual(float(detail["price"]), 10)
		frappe.set_user("Administrator")
		promo = frappe.get_doc(
			{"doctype": "Hosting Promo Code", "code": "P10OFF", "discount_type": "Percentage",
			 "discount_value": 10, "applies_to": "All Orders"}
		).insert()
		frappe.set_user(self.user_a)
		quote = catalog.validate_coupon.__wrapped__("P10OFF", self.product)
		self.assertGreater(float(quote["discount"]), 0)
		with self.assertRaises(frappe.ValidationError):
			catalog.validate_coupon.__wrapped__("NOPE", self.product)
		_ = promo

	def test_cart_checkout_and_orders(self):
		orders.cart_add.__wrapped__(self.product, 2)
		cart = orders.get_cart.__wrapped__()
		self.assertEqual(cart["total"], 20)
		out = orders.checkout.__wrapped__("phase10-order-1")
		self.assertEqual(out["status"], "Payment Pending")
		self.assertEqual(orders.get_cart.__wrapped__()["items"], [])
		dup = orders.checkout.__wrapped__("phase10-order-1")
		self.assertTrue(dup.get("duplicate_request"))
		mine = orders.list_orders.__wrapped__()
		self.assertTrue([o for o in mine["orders"] if o["name"] == out["order"]])
		detail = orders.get_order.__wrapped__(out["order"])
		self.assertEqual(detail["total_amount"], 20)

	def test_checkout_with_coupon_redeems_once(self):
		frappe.set_user("Administrator")
		frappe.get_doc(
			{"doctype": "Hosting Promo Code", "code": "P10ONE", "discount_type": "Fixed Amount",
			 "discount_value": 4, "applies_to": "All Orders", "usage_limit": 5}
		).insert()
		frappe.set_user(self.user_a)
		orders.cart_add.__wrapped__(self.product, 1)
		orders.cart_coupon.__wrapped__("P10ONE")
		out = orders.checkout.__wrapped__("phase10-order-2")
		self.assertEqual(out["total"], 6)
		self.assertEqual(int(frappe.db.get_value("Hosting Promo Code", {"code": "P10ONE"}, "used_count")), 1)

	def test_invoices_and_payment(self):
		inv = ledger.issue_invoice(
			self.user_a, [{"description": "due", "qty": 1, "unit_price": 25, "line_total": 25}],
			currency="USD", idempotency_key="phase10-inv-1")
		rows = billing.list_invoices.__wrapped__()
		self.assertTrue([i for i in rows["invoices"] if i["name"] == inv.name])
		got = billing.get_invoice.__wrapped__(inv.name)
		self.assertEqual(got["outstanding_amount"], 25)
		frappe.set_user("Administrator")
		gw = frappe.get_doc(
			{"doctype": "Hosting Payment Gateway", "gateway_name": "P10 GW",
			 "provider": "Test Gateway", "supported_currencies": "USD",
			 "default_currency": "USD", "is_active": 1}
		).insert()
		frappe.set_user(self.user_a)
		pay = billing.pay_invoice.__wrapped__(inv.name, gw.name, idempotency_key="phase10-pay-1")
		self.assertEqual(pay["status"], "Created")
		st = billing.payment_status.__wrapped__(pay["payment"])
		self.assertEqual(st["invoice"], inv.name)
		again = billing.pay_invoice.__wrapped__(inv.name, gw.name, idempotency_key="phase10-pay-1")
		self.assertEqual(again["payment"], pay["payment"])


class TestPortalServices(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		self.user_a = ensure_user("phase10a@example.com")
		self.user_b = ensure_user("phase10b@example.com")
		self.customer_a = ensure_customer(self.user_a, "A Buyer")
		self.customer_b = ensure_customer(self.user_b, "B Buyer")
		grant_customer_role(self.user_a)
		grant_customer_role(self.user_b)
		self.small = ensure_product("Phase10 Small", 10)
		self.big = ensure_product("Phase10 Big", 30)
		self.service = frappe.get_doc(
			{"doctype": "Hosting Service", "customer": self.customer_a,
			 "status": "Pending", "product": self.small, "billing_cycle": "Monthly"}
		).insert()
		for target in ("Provisioning", "Active"):
			self.service.reload()
			self.service.status = target
			self.service.save(ignore_permissions=True)
		self.sub = frappe.get_doc(
			{
				"doctype": "Hosting Subscription",
				"customer": self.user_a,
				"product": self.small,
				"status": "Active",
				"billing_cycle": "Monthly",
				"amount": 10,
				"currency": "USD",
				"next_renewal_date": add_days(today(), 20),
				"current_period_start": today(),
				"current_period_end": add_days(today(), 29),
			}
		).insert()
		self.service.subscription = self.sub.name
		self.service.save(ignore_permissions=True)
		frappe.set_user(self.user_a)

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_dashboard_and_detail(self):
		dash = services.service_dashboard.__wrapped__()
		self.assertTrue([s for s in dash["services"] if s["name"] == self.service.name])
		detail = services.service_detail.__wrapped__(self.service.name)
		self.assertEqual(detail["status"], "Active")
		frappe.set_user(self.user_b)
		with self.assertRaises(frappe.PermissionError):
			services.service_detail.__wrapped__(self.service.name)

	def test_power_cycle(self):
		off = services.power.__wrapped__(self.service.name, "poweroff")
		self.assertEqual(off["status"], "Succeeded")
		self.assertEqual(frappe.db.get_value("Hosting Service", self.service.name, "status"), "Suspended")
		on = services.power.__wrapped__(self.service.name, "poweron")
		self.assertEqual(on["status"], "Succeeded")
		rb = services.power.__wrapped__(self.service.name, "reboot")
		self.assertEqual(rb["status"], "Succeeded")
		with self.assertRaises(frappe.ValidationError):
			services.power.__wrapped__(self.service.name, "explode")
		frappe.set_user(self.user_b)
		with self.assertRaises(frappe.PermissionError):
			services.power.__wrapped__(self.service.name, "reboot")

	def test_console_single_use_ticket(self):
		frappe.set_user("Administrator")
		account = frappe.get_doc(
			{"doctype": "Hosting Provider Account", "provider_name": "P10 Proxmox",
			 "provider_type": "Proxmox VE"}
		).insert()
		frappe.db.set_value("Hosting Service", self.service.name, "provider_account", account.name)
		frappe.set_user(self.user_a)
		issued = services.console_url.__wrapped__(self.service.name)
		self.assertTrue(issued["ticket"])
		self.assertIn("http", issued["url"])
		redeemed = services.console_ticket.__wrapped__(issued["ticket"])
		self.assertEqual(redeemed["service"], self.service.name)
		with self.assertRaises(frappe.PermissionError):
			services.console_ticket.__wrapped__(issued["ticket"])

	def test_password_reset_and_reinstall(self):
		pw = services.password_reset.__wrapped__(self.service.name, "pw-1", confirm=True)
		self.assertEqual(pw["status"], "Completed")
		dup = services.password_reset.__wrapped__(self.service.name, "pw-1", confirm=True)
		self.assertTrue(dup.get("duplicate_request"))
		with self.assertRaises(frappe.ValidationError):
			services.password_reset.__wrapped__(self.service.name, "pw-2", confirm=False)
		with self.assertRaises(frappe.ValidationError):
			services.os_reinstall.__wrapped__(self.service.name, "os-1", confirm=True,
											  acknowledge_data_loss=False)
		os_done = services.os_reinstall.__wrapped__(self.service.name, "os-1", confirm=True,
													acknowledge_data_loss=True)
		self.assertEqual(os_done["status"], "Completed")

	def test_change_plan(self):
		out = services.change_plan.__wrapped__(self.service.name, self.big,
											   idempotency_key="phase10-mod-1")
		self.assertGreater(float(out["proration_amount"]), 0)
		dup = services.change_plan.__wrapped__(self.service.name, self.big,
											   idempotency_key="phase10-mod-1")
		self.assertEqual(dup["request"], out["request"])


class TestPortalAssetsAndSupport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wipe()

	def setUp(self):
		wipe()
		frappe.set_user("Administrator")
		ensure_status()
		self.user_a = ensure_user("phase10a@example.com")
		self.user_b = ensure_user("phase10b@example.com")
		self.customer_a = ensure_customer(self.user_a, "A Buyer")
		self.customer_b = ensure_customer(self.user_b, "B Buyer")
		grant_customer_role(self.user_a)
		grant_customer_role(self.user_b)
		self.product = ensure_product()
		self.service = frappe.get_doc(
			{"doctype": "Hosting Service", "customer": self.customer_a,
			 "status": "Pending", "product": self.product, "billing_cycle": "Monthly"}
		).insert()
		for target in ("Provisioning", "Active"):
			self.service.reload()
			self.service.status = target
			self.service.save(ignore_permissions=True)
		from beaverbill.beaverbill import domains as domain_engine

		reg = domain_engine.register_domain(self.customer_a, "phase10portal.com",
											service=self.service.name)
		self.domain = reg["domain"]
		frappe.set_user(self.user_a)

	def tearDown(self):
		frappe.set_user("Administrator")
		wipe()

	def test_domain_and_dns(self):
		mine = assets.my_domains.__wrapped__()
		self.assertTrue([d for d in mine["domains"] if d["name"] == self.domain])
		detail = assets.domain_detail.__wrapped__(self.domain)
		self.assertEqual(detail["domain_name"], "phase10portal.com")
		rec = assets.dns_add.__wrapped__(self.domain, "A", "www", "203.0.113.9")
		self.assertTrue(rec["record"])
		assets.dns_remove.__wrapped__(rec["record"])
		frappe.set_user(self.user_b)
		with self.assertRaises(frappe.PermissionError):
			assets.dns_add.__wrapped__(self.domain, "A", "x", "203.0.113.8")

	def test_certificates_and_backups(self):
		req = assets.request_certificate.__wrapped__(self.domain, service=self.service.name)
		self.assertEqual(frappe.db.get_value("SSL Certificate", req["certificate"], "customer"),
						 self.customer_a)
		mine = assets.my_certificates.__wrapped__()
		self.assertTrue(mine["certificates"])
		policy = frappe.get_doc(
			{"doctype": "Backup Policy", "policy_name": "P10 Pol", "service": self.service.name,
			 "frequency": "Manual", "retention_count": 3, "retention_days": 7, "enabled": 1}
		).insert(ignore_permissions=True)
		from beaverbill.beaverbill import backups as backup_engine

		frappe.set_user("Administrator")
		ran = backup_engine.run_backup(policy.name)
		frappe.set_user(self.user_a)
		rows = assets.my_backups.__wrapped__()
		self.assertTrue([b for b in rows["backups"] if b["name"] == ran["backup"]])
		req = assets.request_restore.__wrapped__(ran["backup"], self.service.name)
		st = assets.restore_status.__wrapped__(req["restore"])
		self.assertEqual(st["status"], "Pending")
		frappe.set_user(self.user_b)
		with self.assertRaises(frappe.PermissionError):
			assets.restore_status.__wrapped__(req["restore"])

	def test_addons_and_usage(self):
		frappe.set_user("Administrator")
		row = frappe.get_doc(
			{"doctype": "Hosting Product Addon", "addon_name": "P10 Disk",
			 "product": self.product, "price": 3}
		).insert()
		frappe.set_user(self.user_a)
		out = assets.order_addon.__wrapped__(self.service.name, row.name, "phase10-ao-1")
		self.assertEqual(out["status"], "Active")
		mine = assets.my_addons.__wrapped__()
		self.assertTrue(mine["addons"])
		off = assets.cancel_addon.__wrapped__(out["addon"], mode="Immediate")
		self.assertEqual(off["status"], "Cancelled")
		from beaverbill.beaverbill import backups as backup_engine

		frappe.set_user("Administrator")
		backup_engine.record_storage_usage(self.service.name, used_gb=10, quota_gb=50)
		frappe.set_user(self.user_a)
		usage = services.service_usage.__wrapped__(self.service.name)
		self.assertEqual(len(usage["storage_snapshots"]), 1)
		store = assets.storage_usage.__wrapped__(self.service.name)
		self.assertEqual(len(store["snapshots"]), 1)

	def test_tickets_and_notifications(self):
		opened = support.create_ticket.__wrapped__("Portal is slow", "Dashboard loads slowly",
												   service=self.service.name)
		self.assertTrue(opened["ticket"])
		mine = support.my_tickets.__wrapped__()
		self.assertTrue([t for t in mine["tickets"] if t["name"] == opened["ticket"]])
		detail = support.ticket_detail.__wrapped__(opened["ticket"])
		self.assertIn(self.service.name, detail["description"])
		reply = support.ticket_reply.__wrapped__(opened["ticket"], "Any update?")
		self.assertTrue(reply["reply"])
		with self.assertRaises(frappe.ValidationError):
			support.create_ticket.__wrapped__("Bad attach", "x", attachments='["/files/ghost.png"]')
		frappe.set_user(self.user_b)
		with self.assertRaises(frappe.PermissionError):
			support.ticket_detail.__wrapped__(opened["ticket"])
		frappe.set_user(self.user_a)
		feed = support.list_notifications.__wrapped__()
		self.assertTrue(feed["notifications"])
		count = support.unread_count.__wrapped__()
		self.assertGreater(count["unread"], 0)
		support.mark_read.__wrapped__(feed["notifications"][0]["name"])
		after = support.unread_count.__wrapped__()
		self.assertEqual(after["unread"], count["unread"] - 1)
