"""Phase 5 gateway layer: intents, provider adapters, retry, reconciliation.

Beaver Bill rows stay the source of truth. `frappe/payments` controllers
supply checkout URLs when the provider maps to one. Amounts always come
from the invoice on the server. The client never sets the amount.
"""

import json

import frappe
from frappe.utils import add_to_date, now_datetime, today

PROVIDERS = ("Test Gateway", "Razorpay", "Stripe")

# Gateway event type -> Hosting Payment Transaction status.
EVENT_MAP = {
	"Test Gateway": {
		"payment.authorized": "Authorized",
		"payment.captured": "Captured",
		"payment.failed": "Failed",
		"refund.processed": "Refunded",
		"charge.disputed": "Chargeback",
	},
	"Razorpay": {
		"payment.authorized": "Authorized",
		"payment.captured": "Captured",
		"payment.failed": "Failed",
		"refund.processed": "Refunded",
		"refund.failed": "Failed",
	},
	"Stripe": {
		"payment_intent.succeeded": "Captured",
		"payment_intent.payment_failed": "Failed",
		"charge.refunded": "Refunded",
		"charge.dispute.created": "Chargeback",
	},
}


class GatewayOutage(Exception):
	pass


def _require_staff():
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles & {"System Manager", "Hosting Admin"}:
		frappe.throw("Only billing staff may run this action", frappe.PermissionError)


def _gateway(name):
	doc = frappe.get_doc("Hosting Payment Gateway", name)
	if not doc.is_active:
		frappe.throw(f"Gateway {name} is not active", frappe.ValidationError)
	return doc


def _key(value=None):
	return value or f"gw-{frappe.generate_hash(length=12)}"


class TestGatewayAdapter:
	"""Offline provider for tests and local checkout. No network calls."""

	name = "Test Gateway"

	def create_order(self, amount, currency, receipt):
		return {"id": f"test_order_{receipt}", "status": "created"}

	def fetch_payment(self, reference):
		rows = frappe.get_all(
			"Hosting Payment Event",
			filters={"event_id": ["like", f"%{reference}%"]},
			fields=["event_type", "status"],
			limit=1,
		)
		if rows and rows[0].status == "Processed":
			return {"status": "known", "event_type": rows[0].event_type}
		return {"status": "unknown"}


class PaymentsAppAdapter:
	"""Thin wrapper over frappe/payments controllers for real providers."""

	name = "payments"

	def __init__(self, provider):
		self.provider = provider

	def _controller(self):
		from payments.utils.utils import get_payment_gateway_controller

		return get_payment_gateway_controller(self.provider)

	def get_payment_url(self, **kwargs):
		return self._controller().get_payment_url(**kwargs)

	def create_order(self, amount, currency, receipt):
		return {"id": f"{self.provider.lower()}_order_{receipt}", "status": "created"}

	def fetch_payment(self, reference):
		return {"status": "unknown", "manual": True}


def get_provider_adapter(gateway):
	if gateway.provider == "Test Gateway":
		return TestGatewayAdapter()
	return PaymentsAppAdapter(gateway.provider)


def target_status_for(provider, event_type):
	return EVENT_MAP.get(provider, {}).get(event_type)


def create_payment_intent(
	customer: str,
	invoice_name: str,
	gateway_name: str,
	payment_method: str | None = None,
	idempotency_key: str | None = None,
):
	"""Create a server-side payment intent for an invoice outstanding amount."""
	if idempotency_key:
		existing = frappe.db.get_value("Hosting Payment Transaction", {"idempotency_key": idempotency_key}, "name")
		if existing:
			return frappe.get_doc("Hosting Payment Transaction", existing)
	invoice = frappe.get_doc("Hosting Invoice", invoice_name)
	outstanding = float(invoice.total_amount or 0) - float(invoice.paid_amount or 0)
	if outstanding <= 0:
		frappe.throw(f"Invoice {invoice_name} has nothing outstanding", frappe.ValidationError)
	gateway = _gateway(gateway_name)
	currency = (invoice.currency or gateway.default_currency or "USD").upper()
	if currency not in gateway.currencies():
		frappe.throw(f"Gateway {gateway_name} does not support {currency}", frappe.ValidationError)
	token_ref = None
	if payment_method:
		method = frappe.get_doc("Hosting Payment Method", payment_method)
		if method.customer != customer or method.gateway != gateway_name:
			frappe.throw("Payment method does not belong to this customer and gateway", frappe.ValidationError)
		token_ref = method.token_reference
	payment = frappe.get_doc(
		{
			"doctype": "Hosting Payment Transaction",
			"customer": customer,
			"payment_date": today(),
			"amount": outstanding,
			"currency": currency,
			"status": "Created",
			"gateway": gateway_name,
			"payment_token_ref": token_ref,
			"source_invoice": invoice_name,
			"idempotency_key": _key(idempotency_key),
		}
	).insert()
	try:
		if gateway.maintenance_mode:
			raise GatewayOutage(f"Gateway {gateway_name} is in maintenance")
		order = get_provider_adapter(gateway).create_order(outstanding, currency, payment.name)
		payment.gateway_reference = order.get("id")
		payment.save()
	except Exception as exc:
		schedule_retry(payment.name, str(exc))
		raise GatewayOutage(str(exc)) from exc
	return payment


def schedule_retry(payment_name: str, error: str):
	"""Mark a pre-capture payment Failed with exponential backoff."""
	payment = frappe.get_doc("Hosting Payment Transaction", payment_name)
	if payment.status not in ("Created", "Authorized"):
		frappe.throw(f"Payment {payment.status} cannot be retried", frappe.ValidationError)
	gateway = frappe.get_doc("Hosting Payment Gateway", payment.gateway) if payment.gateway else None
	backoff = int((gateway.retry_backoff_minutes if gateway else 30) or 30)
	count = int(payment.retry_count or 0) + 1
	payment.retry_count = count
	payment.last_error = (error or "")[:1000]
	payment.next_retry_at = add_to_date(now_datetime(), minutes=backoff * (2 ** (count - 1)))
	payment.status = "Failed"
	payment.save()
	return payment


@frappe.whitelist()
def retry_failed_payment(payment_name: str) -> str:
	"""Staff action: re-attempt a failed payment. Terminal after max retries."""
	_require_staff()
	payment = frappe.get_doc("Hosting Payment Transaction", payment_name)
	if payment.status != "Failed":
		frappe.throw(f"Only failed payments can be retried, not {payment.status}", frappe.ValidationError)
	gateway = _gateway(payment.gateway)
	if int(payment.retry_count or 0) >= int(gateway.max_retries or 0):
		frappe.throw("Max retries reached for this payment", frappe.ValidationError)
	if payment.next_retry_at and payment.next_retry_at > now_datetime():
		frappe.throw("Next retry is not due yet", frappe.ValidationError)
	payment.status = "Created"
	payment.next_retry_at = None
	payment.save()
	try:
		if gateway.maintenance_mode:
			raise GatewayOutage(f"Gateway {gateway.name} is in maintenance")
		order = get_provider_adapter(gateway).create_order(
			float(payment.amount), payment.currency, payment.name
		)
		payment.gateway_reference = order.get("id")
		payment.save()
	except Exception as exc:
		schedule_retry(payment.name, str(exc))
		raise GatewayOutage(str(exc)) from exc
	return payment.name


def fetch_remote_status(payment_name: str) -> dict:
	payment = frappe.get_doc("Hosting Payment Transaction", payment_name)
	if not payment.gateway:
		return {"status": "unknown", "reason": "no gateway linked"}
	gateway = frappe.get_doc("Hosting Payment Gateway", payment.gateway)
	adapter = get_provider_adapter(gateway)
	return adapter.fetch_payment(payment.gateway_reference or payment.name)


def reconcile_gateway(gateway_name: str) -> dict:
	"""Compare local payments against stored gateway events."""
	_gateway(gateway_name)
	stuck = frappe.get_all(
		"Hosting Payment Transaction",
		filters={"gateway": gateway_name, "status": ["in", ["Created", "Authorized"]]},
		fields=["name", "amount", "currency", "status", "modified"],
	)
	stuck_names = {row.name for row in stuck}
	linked = set(
		frappe.get_all(
			"Hosting Payment Event",
			filters={"gateway": gateway_name, "status": "Processed"},
			pluck="payment",
		)
	)
	orphans = frappe.get_all(
		"Hosting Payment Event",
		filters={"gateway": gateway_name, "status": "Processed", "payment": ["in", ["", None]]},
		fields=["name", "event_id", "event_type"],
	)
	mismatches = []
	for row in frappe.get_all(
		"Hosting Payment Event",
		filters={"gateway": gateway_name, "status": "Processed", "event_type": ["like", "%captured%"]},
		fields=["name", "payment", "payload"],
	):
		if not row.payment:
			continue
		try:
			body = json.loads(row.payload or "{}")
		except ValueError:
			continue
		amount = _event_amount(body)
		if amount is None:
			continue
		local = frappe.db.get_value("Hosting Payment Transaction", row.payment, "amount")
		if local is not None and abs(float(local) - amount) > 0.01:
			mismatches.append({"event": row.name, "payment": row.payment, "local": local, "remote": amount})
	return {
		"gateway": gateway_name,
		"stuck_payments": [row.name for row in stuck if row.name not in linked],
		"orphan_events": [row.name for row in orphans],
		"amount_mismatches": mismatches,
	}


def _event_amount(body):
	for key in ("amount", "amount_paid"):
		if body.get(key) is not None:
			try:
				return float(body[key])
			except (TypeError, ValueError):
				return None
	data = body.get("data") or {}
	obj = data.get("object") or {}
	if obj.get("amount_received") is not None:
		try:
			return float(obj["amount_received"]) / 100.0
		except (TypeError, ValueError):
			return None
	entity = ((body.get("payload") or {}).get("payment") or {}).get("entity") or {}
	if entity.get("amount") is not None:
		try:
			return float(entity["amount"]) / 100.0
		except (TypeError, ValueError):
			return None
	return None


@frappe.whitelist()
def reconcile_now(gateway_name: str) -> dict:
	_require_staff()
	return reconcile_gateway(gateway_name)
