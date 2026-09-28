import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from beaverbill.beaverbill import billing, subscription_lifecycle, subscriptions


def wipe():
    for dt in [
        "Comment",
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
    ]:
        try:
            for name in frappe.get_all(dt, pluck="name"):
                frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
        except Exception:
            for row in frappe.get_all(dt, fields=["name"]):
                frappe.db.delete(dt, row.name)
    frappe.db.commit()


def ensure_user(email="phase6-buyer@example.com"):
    if not frappe.db.exists("User", email):
        frappe.get_doc(
            {"doctype": "User", "email": email, "first_name": "Phase6", "send_welcome_email": 0}
        ).insert(ignore_permissions=True)
    return email


def ensure_product():
    if not frappe.db.exists("Hosting Product Group", "Phase6 Group"):
        frappe.get_doc({"doctype": "Hosting Product Group", "product_group_name": "Phase6 Group"}).insert()
    if not frappe.db.exists("Hosting Product", "Phase6 VPS"):
        frappe.get_doc(
            {
                "doctype": "Hosting Product",
                "product_name": "Phase6 VPS",
                "product_group": "Phase6 Group",
                "billing_cycle": "Monthly",
                "price": 100,
                "currency": "USD",
            }
        ).insert()


def make_sub(customer, **over):
    status = over.pop("status", "Active")
    doc = {
        "doctype": "Hosting Subscription",
        "customer": customer,
        "product": "Phase6 VPS",
        "status": "Active",
        "billing_cycle": "Monthly",
        "amount": 100,
        "currency": "USD",
        "next_renewal_date": today(),
        "current_period_start": add_days(today(), -30),
        "current_period_end": today(),
        "renewal_lead_days": 3,
        "grace_period_days": 7,
        "max_retries": 2,
        "retry_backoff_minutes": 60,
    }
    doc.update(over)
    sub = frappe.get_doc(doc).insert()
    if status != "Active":
        frappe.db.set_value("Hosting Subscription", sub.name, "status", status, update_modified=False)
        sub.reload()
    extra = {k: v for k, v in over.items() if k in ("last_retry_at", "suspend_reason")}
    for k, v in extra.items():
        frappe.db.set_value("Hosting Subscription", sub.name, k, v, update_modified=False)
    sub.reload()
    return sub


def fund(customer, amount):
    billing.post_ledger(customer, amount, "Credit", "Phase6 funding")


class TestSubscriptionRenewal(IntegrationTestCase):
    def setUp(self):
        wipe()
        frappe.set_user("Administrator")
        self.customer = ensure_user()
        ensure_product()

    def test_illegal_transition_throws(self):
        sub = make_sub(self.customer, status="Active")
        bad = frappe.get_doc("Hosting Subscription", sub.name)
        bad.status = "Archived"
        self.assertRaises(frappe.ValidationError, bad.save)
        legacy = frappe.get_doc("Hosting Subscription", sub.name)
        legacy.status = "Suspended"
        legacy.save()
        self.assertEqual(legacy.status, "Suspended")
        legacy.status = "Active"
        legacy.save()
        self.assertEqual(legacy.status, "Active")

    def test_renewal_with_autopay_advances_period(self):
        fund(self.customer, 500)
        sub = make_sub(self.customer)
        out = subscriptions.process_subscription_renewals()
        self.assertIn(sub.name, out["renewed"])
        sub.reload()
        self.assertEqual(sub.status, "Active")
        self.assertEqual(int(sub.retry_count), 0)
        self.assertTrue(sub.last_invoice)
        inv = frappe.get_doc("Hosting Invoice", sub.last_invoice)
        self.assertEqual(inv.status, "Paid")

    def test_overlapping_runs_create_one_invoice(self):
        fund(self.customer, 500)
        sub = make_sub(self.customer)
        original_period = sub.next_renewal_date
        first = subscriptions.handle_due_renewal(
            frappe.get_doc("Hosting Subscription", sub.name), frappe.utils.getdate(today())
        )
        self.assertEqual(first, "renewed")
        key = subscriptions.renewal_key(sub.name, original_period)
        count = len(frappe.get_all("Hosting Invoice", filters={"idempotency_key": key}))
        self.assertEqual(count, 1)
        sub.reload()
        again = frappe.get_doc("Hosting Invoice", sub.last_invoice)
        self.assertEqual(again.idempotency_key, key)

    def test_failed_payment_backoff_then_grace(self):
        sub = make_sub(self.customer, max_retries=1)
        out = subscriptions.process_subscription_renewals()
        self.assertIn(sub.name, out["payment-failed"])
        sub.reload()
        self.assertEqual(sub.status, "Grace Period")
        self.assertEqual(int(sub.retry_count), 1)
        self.assertIsNotNone(sub.next_retry_at)
        self.assertTrue(sub.last_invoice)

    def test_retry_pays_after_funding(self):
        sub = make_sub(self.customer, max_retries=4)
        subscriptions.process_subscription_renewals()
        sub.reload()
        self.assertEqual(sub.status, "Payment Failed")
        fund(self.customer, 500)
        sub.reload()
        sub.next_retry_at = None
        sub.save()
        subscription_lifecycle.retry_subscription_payment(sub.name)
        sub.reload()
        self.assertEqual(sub.status, "Active")

    def test_grace_expiry_suspends_and_syncs_service(self):
        sub = make_sub(self.customer, status="Grace Period", last_retry_at=add_days(today(), -10))
        svc = frappe.get_doc(
            {
                "doctype": "Hosting Service",
                "customer": self._ensure_hosting_customer(),
                "status": "Pending",
                "product": "Phase6 VPS",
                "subscription": sub.name,
            }
        ).insert()
        frappe.db.set_value("Hosting Service", svc.name, "status", "Active", update_modified=False)
        svc.reload()
        subscriptions.process_subscription_renewals()
        sub.reload()
        self.assertEqual(sub.status, "Suspended")
        svc.reload()
        self.assertEqual(svc.status, "Suspended")

    def test_end_of_period_cancel_then_terminate(self):
        sub = make_sub(self.customer)
        subscription_lifecycle.cancel_subscription(sub.name, mode="end_of_period", reason="leaving")
        sub.reload()
        self.assertEqual(sub.status, "Cancellation Pending")
        self.assertEqual(int(sub.cancel_at_period_end), 1)
        sub.cancellation_effective_at = today()
        sub.save()
        subscriptions.process_subscription_renewals()
        sub.reload()
        self.assertEqual(sub.status, "Terminated")
        self.assertIsNotNone(sub.data_purge_scheduled_at)

    def test_immediate_cancel_posts_unused_credit(self):
        sub = make_sub(
            self.customer,
            current_period_start=today(),
            current_period_end=add_days(today(), 29),
            next_renewal_date=add_days(today(), 29),
        )
        subscription_lifecycle.cancel_subscription(sub.name, mode="immediate", reason="close now")
        sub.reload()
        self.assertEqual(sub.status, "Terminated")
        notes = frappe.get_all("Hosting Credit Note", filters={"customer": self.customer})
        self.assertTrue(notes)
        self.assertIsNotNone(sub.data_purge_scheduled_at)

    def test_reinstate_clears_flags(self):
        sub = make_sub(self.customer, status="Suspended", suspend_reason="unpaid")
        subscription_lifecycle.reinstate_subscription(sub.name)
        sub.reload()
        self.assertEqual(sub.status, "Active")
        self.assertEqual(int(sub.reinstatement_count), 1)
        self.assertEqual(int(sub.retry_count), 0)

    def test_purge_due_lists_terminated(self):
        sub = make_sub(self.customer, status="Terminated")
        sub.db_set("data_purge_scheduled_at", today(), update_modified=False)
        due = subscription_lifecycle.purge_due()
        self.assertIn(sub.name, due)

    def _ensure_hosting_customer(self):
        name = frappe.db.get_value("Hosting Customer", {"primary_user": self.customer}, "name")
        if name:
            return name
        return frappe.get_doc(
            {
                "doctype": "Hosting Customer",
                "customer_name": "Phase6 Buyer",
                "primary_user": self.customer,
                "status": "Active",
            }
        ).insert().name
