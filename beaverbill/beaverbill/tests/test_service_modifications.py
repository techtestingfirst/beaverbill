import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from beaverbill.beaverbill import billing, modification_apply, modifications


def wipe():
    for dt in [
        "Hosting Service Modification Request",
        "Hosting Modification Event",
        "Hosting Service",
        "Hosting Subscription",
        "Hosting Payment Allocation",
        "Hosting Payment Transaction",
        "Hosting Refund",
        "Hosting Credit Note",
        "Hosting Invoice Item",
        "Hosting Invoice",
        "Customer Credit Transaction",
        "Hosting Order",
        "Hosting Product",
    ]:
        for name in frappe.get_all(dt, pluck="name"):
            frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
    frappe.db.commit()


def ensure_user(email="phase7-buyer@example.com"):
    if not frappe.db.exists("User", email):
        frappe.get_doc(
            {"doctype": "User", "email": email, "first_name": "Phase7", "send_welcome_email": 0}
        ).insert(ignore_permissions=True)
    return email


def ensure_product(name, price, cycle="Monthly", specs=None):
    if not frappe.db.exists("Hosting Product Group", "Phase7 Group"):
        frappe.get_doc({"doctype": "Hosting Product Group", "product_group_name": "Phase7 Group"}).insert()
    if frappe.db.exists("Hosting Product", name):
        return name
    doc = {
        "doctype": "Hosting Product",
        "product_name": name,
        "product_group": "Phase7 Group",
        "billing_cycle": cycle,
        "price": price,
        "currency": "USD",
    }
    doc.update(specs or {})
    return frappe.get_doc(doc).insert().name


def ensure_hosting_customer(user):
    name = frappe.db.get_value("Hosting Customer", {"primary_user": user}, "name")
    if name:
        return name
    return frappe.get_doc(
        {"doctype": "Hosting Customer", "customer_name": "Phase7 Buyer", "primary_user": user, "status": "Active"}
    ).insert().name


def make_sub(customer, product="Phase7 Small", amount=10.0, **over):
    doc = {
        "doctype": "Hosting Subscription",
        "customer": customer,
        "product": product,
        "status": "Active",
        "billing_cycle": "Monthly",
        "amount": amount,
        "currency": "USD",
        "next_renewal_date": add_days(today(), 15),
        "current_period_start": today(),
        "current_period_end": add_days(today(), 29),
    }
    doc.update(over)
    return frappe.get_doc(doc).insert()


def make_service(customer_name, sub):
    svc = frappe.get_doc(
        {"doctype": "Hosting Service", "customer": customer_name, "status": "Pending", "product": sub.product, "subscription": sub.name}
    ).insert()
    frappe.db.set_value("Hosting Service", svc.name, "status", "Active", update_modified=False)
    return frappe.get_doc("Hosting Service", svc.name)


def legacy_proration(sub, new_price):
    from beaverbill.beaverbill.doctype.hosting_service_modification_request.hosting_service_modification_request import (
        HostingServiceModificationRequest,
    )

    probe = HostingServiceModificationRequest(
        {"doctype": "Hosting Service Modification Request", "subscription": sub.name, "new_product": "Phase7 Large"}
    )
    probe.calculate_proration()
    return float(probe.proration_amount)


class TestServiceModifications(IntegrationTestCase):
    def setUp(self):
        wipe()
        frappe.set_user("Administrator")
        self.customer = ensure_user()
        self.hc = ensure_hosting_customer(self.customer)
        ensure_product("Phase7 Small", 10.0)
        ensure_product("Phase7 Large", 30.0)
        ensure_product("Phase7 Big", 40.0, specs={"cpu_cores": 8, "ram_mb": 16384, "disk_gb": 320})
        ensure_product("Phase7 Tiny", 5.0, specs={"cpu_cores": 1, "ram_mb": 1024, "disk_gb": 25})

    def test_proration_compat_across_cycles(self):
        for cycle in ("Monthly", "Quarterly", "Semi-Annually", "Annually"):
            sub = make_sub(self.customer, next_renewal_date=add_days(today(), 15))
            frappe.db.set_value("Hosting Subscription", sub.name, "billing_cycle", cycle,
                                update_modified=False)
            sub.reload()
            self.assertAlmostEqual(
                modifications.compute_proration(sub, 30.0), legacy_proration(sub, 30.0), places=2
            )
        due = make_sub(self.customer, next_renewal_date=today())
        self.assertEqual(modifications.compute_proration(due, 30.0), 30.0)
        past = make_sub(self.customer, next_renewal_date=add_days(today(), -3))
        self.assertEqual(modifications.compute_proration(past, 30.0), 30.0)

    def test_snapshots_frozen_at_request(self):
        sub = make_sub(self.customer)
        req = modifications.request_modification(sub.name, "Phase7 Large")
        self.assertEqual(req.old_product, "Phase7 Small")
        self.assertEqual(float(req.old_amount), 10.0)
        old = json.loads(req.old_product_snapshot)
        new = json.loads(req.new_product_snapshot)
        self.assertEqual(old["price"], 10.0)
        self.assertEqual(new["price"], 30.0)
        self.assertTrue(req.events)

    def test_immediate_upgrade_invoice_then_apply(self):
        sub = make_sub(self.customer)
        req = modifications.request_modification(sub.name, "Phase7 Large")
        modifications.approve_modification(req.name)
        req.reload()
        self.assertEqual(req.status, "Approved")
        self.assertTrue(req.invoice)
        inv = frappe.get_doc("Hosting Invoice", req.invoice)
        self.assertEqual(inv.status, "Issued")
        inv.status = "Paid"
        inv.paid_amount = inv.total_amount
        inv.save()
        modification_apply.apply_modification(req.name)
        req.reload()
        sub.reload()
        self.assertEqual(req.status, "Completed")
        self.assertEqual(sub.product, "Phase7 Large")
        self.assertEqual(float(sub.amount), 30.0)

    def test_next_cycle_defers_invoice_and_apply(self):
        sub = make_sub(self.customer)
        req = modifications.request_modification(sub.name, "Phase7 Large", effective_mode="Next Cycle")
        self.assertEqual(req.effective_mode, "Next Cycle")
        modifications.approve_modification(req.name)
        req.reload()
        self.assertFalse(req.invoice)
        self.assertEqual(modification_apply.apply_due_modifications(), [])
        req.reload()
        self.assertEqual(req.status, "Approved")
        # First attempt at the effective date raises the invoice for payment.
        self.assertRaises(
            frappe.ValidationError, modification_apply.apply_modification, req.name
        )
        req.reload()
        self.assertTrue(req.invoice)
        inv = frappe.get_doc("Hosting Invoice", req.invoice)
        inv.status = "Paid"
        inv.paid_amount = inv.total_amount
        inv.save()
        done = modification_apply.apply_due_modifications(as_of=add_days(today(), 30))
        self.assertEqual(done, [req.name])
        req.reload()
        sub.reload()
        self.assertEqual(req.status, "Completed")
        self.assertEqual(sub.product, "Phase7 Large")

    def test_next_cycle_apply_needs_payment(self):
        sub = make_sub(self.customer)
        req = modifications.request_modification(sub.name, "Phase7 Large", effective_mode="Next Cycle")
        modifications.approve_modification(req.name)
        self.assertRaises(
            frappe.ValidationError,
            modification_apply.apply_modification, req.name,
        )

    def test_downgrade_usage_block(self):
        ensure_product("Phase7 Mid", 20.0, specs={"cpu_cores": 4, "ram_mb": 8192, "disk_gb": 160})
        sub = make_sub(self.customer, product="Phase7 Big", amount=40.0)
        svc = make_service(self.hc, sub)
        svc.upstream_metadata = json.dumps({"usage": {"disk_gb": 200}})
        svc.save()
        self.assertRaises(
            frappe.ValidationError,
            modifications.request_modification, sub.name, "Phase7 Tiny", service=svc.name,
        )

    def test_downgrade_warning_requires_ack(self):
        sub = make_sub(self.customer, product="Phase7 Big", amount=40.0)
        self.assertRaises(
            frappe.ValidationError,
            modifications.request_modification, sub.name, "Phase7 Tiny",
        )
        req = modifications.request_modification(
            sub.name, "Phase7 Tiny", data_loss_acknowledged=True
        )
        self.assertIn("disk_gb", req.downgrade_warnings)
        modifications.approve_modification(req.name)
        modification_apply.apply_modification(req.name)
        req.reload()
        sub.reload()
        self.assertEqual(req.status, "Completed")
        self.assertEqual(sub.product, "Phase7 Tiny")
        self.assertTrue(req.credit_transaction)

    def test_idempotent_request_and_approve(self):
        sub = make_sub(self.customer)
        first = modifications.request_modification(
            sub.name, "Phase7 Large", idempotency_key="mod-p7-1"
        )
        second = modifications.request_modification(
            sub.name, "Phase7 Large", idempotency_key="mod-p7-1"
        )
        self.assertEqual(first.name, second.name)
        modifications.approve_modification(first.name)
        modifications.approve_modification(first.name)
        invoices = frappe.get_all("Hosting Invoice", filters={"idempotency_key": "mod-p7-1-invoice"})
        self.assertEqual(len(invoices), 1)

    def test_concurrent_request_blocked(self):
        sub = make_sub(self.customer)
        modifications.request_modification(sub.name, "Phase7 Large")
        self.assertRaises(
            frappe.ValidationError,
            modifications.request_modification, sub.name, "Phase7 Big",
        )

    def test_failed_resize_rolls_back_and_compensates(self):
        sub = make_sub(self.customer)
        svc = make_service(self.hc, sub)
        req = modifications.request_modification(sub.name, "Phase7 Large", service=svc.name)
        modifications.approve_modification(req.name)
        req.reload()
        inv = frappe.get_doc("Hosting Invoice", req.invoice)
        inv.status = "Paid"
        inv.paid_amount = inv.total_amount
        inv.save()
        real = modification_apply.resize_service_resources
        modification_apply.resize_service_resources = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("resize exploded")
        )
        try:
            self.assertRaises(Exception, modification_apply.apply_modification, req.name)
        finally:
            modification_apply.resize_service_resources = real
        req.reload()
        sub.reload()
        self.assertEqual(req.status, "Failed")
        self.assertEqual(sub.product, "Phase7 Small")
        self.assertEqual(float(sub.amount), 10.0)
        self.assertEqual(frappe.db.get_value("Hosting Invoice", req.invoice, "status"), "Paid")
        self.assertTrue(req.failure_reason)
        modification_apply.compensate_modification(req.name)
        req.reload()
        self.assertEqual(req.status, "Compensated")
        notes = frappe.get_all("Hosting Credit Note", filters={"customer": self.customer})
        self.assertTrue(notes)

    def test_policy_blocks_unusable_subscriptions(self):
        sub = make_sub(self.customer)
        for status in ("Suspended", "Terminated", "Cancellation Pending"):
            frappe.db.set_value("Hosting Subscription", sub.name, "status", status,
                                update_modified=False)
            self.assertRaises(
                frappe.ValidationError,
                modifications.request_modification, sub.name, "Phase7 Large",
            )
            frappe.db.set_value("Hosting Subscription", sub.name, "status", "Active",
                                update_modified=False)
