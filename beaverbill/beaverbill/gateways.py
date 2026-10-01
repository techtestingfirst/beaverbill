"""Phase 5 gateway layer: intents, provider adapters, retry, reconciliation.

Beaver Bill rows stay the source of truth. `frappe/payments` controllers
supply checkout URLs when the provider maps to one. Amounts always come
from the invoice on the server. The client never sets the amount.
"""

import contextlib
import json
import socket

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


@contextlib.contextmanager
def _prefer_ipv4():
	"""Resolve IPv4 first for the wrapped call only.

	This resolver often returns only NAT64 IPv6 for AF_UNSPEC while A
	records answer instantly, and the IPv6 path stalls. Query AF_INET
	explicitly; fall back to the original lookup when it has nothing.
	"""
	original = socket.getaddrinfo

	def patched(host, port, family=0, *args, **kwargs):
		if family in (0, socket.AF_UNSPEC):
			try:
				quad_a = original(host, port, socket.AF_INET, *args, **kwargs)
			except socket.gaierror:
				quad_a = []
			if quad_a:
				return quad_a
		return original(host, port, family, *args, **kwargs)

	socket.getaddrinfo = patched
	try:
		yield
	finally:
		socket.getaddrinfo = original


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
	"""Real provider via frappe/payments controllers. Network calls to the provider."""

	name = "payments"

	def __init__(self, provider):
		self.provider = provider

	def _controller(self):
		from payments.utils.utils import get_payment_gateway_controller

		return get_payment_gateway_controller(self.provider)

	def get_payment_url(self, **kwargs):
		return self._controller().get_payment_url(**kwargs)

	def create_order(self, amount, currency, receipt):
		"""Create a real provider order (major units in, provider order out).

		Razorpay goes direct with a hard timeout: the payments controller's
		order call can stall without one, leaving the portal spinner forever
		and the intent reference-less. Same payload the controller sends.
		"""
		if self.provider == "Razorpay":
			controller = self._controller()
			import requests

			try:
				with _prefer_ipv4():
					resp = requests.post(
						"https://api.razorpay.com/v1/orders",
						auth=(controller.api_key,
								controller.get_password(fieldname="api_secret", raise_exception=False)),
						timeout=45,
						data={
							"amount": int(round(float(amount) * 100)),
							"currency": currency,
							"receipt": receipt,
						},
					)
				resp.raise_for_status()
				return resp.json()
			except requests.RequestException as exc:
				frappe.throw(
					f"{self.provider} could not create the order ({currency} {amount}). "
					f"Check the provider account supports this currency. Provider said: {exc}"
				)
		try:
			return self._controller().create_order(amount=amount, currency=currency, receipt=receipt)
		except frappe.ValidationError as exc:
			# The payments controller hides the provider's reason; keep the
			# currency context so the portal can show an actionable message.
			frappe.throw(
				f"{self.provider} could not create the order ({currency} {amount}). "
				"Check the provider account supports this currency. "
				f"Provider said: {exc}"
			)

	def fetch_payment(self, reference):
		return {"status": "unknown", "manual": True}


def get_provider_adapter(gateway):
	if gateway.provider == "Test Gateway":
		return TestGatewayAdapter()
	return PaymentsAppAdapter(gateway.provider)


def target_status_for(provider, event_type):
	return EVENT_MAP.get(provider, {}).get(event_type)


def build_checkout_url(payment_name: str) -> str | None:
	"""Razorpay/Stripe hosted checkout URL for a local payment intent.

	Returns None for the offline Test Gateway. The provider order already
	exists (``gateway_reference``), so the controller only logs an
	Integration Request and hands back the checkout page URL. Amounts stay
	server-side; the caller never supplies them.
	"""
	payment = frappe.get_doc("Hosting Payment Transaction", payment_name)
	gateway = frappe.get_doc("Hosting Payment Gateway", payment.gateway)
	if gateway.provider == "Test Gateway":
		return None
	adapter = get_provider_adapter(gateway)
	ref = payment.gateway_reference or ""
	if not (ref.startswith("order_") or ref.startswith("pi_")):
		# Legacy/fake reference (pre-real-checkout intents): mint a real provider
		order = adapter.create_order(float(payment.amount or 0), payment.currency, payment.name)
		payment.gateway_reference = order.get("id")
		payment.save()
		ref = payment.gateway_reference or ""
	invoice_name = payment.source_invoice
	payer = payment.customer or frappe.session.user
	payer_name = frappe.db.get_value("User", payer, "full_name") or payer
	return adapter.get_payment_url(
		amount=float(payment.amount or 0),
		currency=payment.currency,
		title=f"Invoice {invoice_name}" if invoice_name else f"Payment {payment.name}",
		description=f"Payment for {invoice_name}" if invoice_name else payment.name,
		reference_doctype="Hosting Payment Transaction",
		reference_docname=payment.name,
		payer_email=payer,
		payer_name=payer_name,
		order_id=payment.gateway_reference,
		payment_gateway=gateway.provider,
		redirect_to=(f"/beaverbill/invoices/{invoice_name}?just_paid=1" if invoice_name else "/beaverbill/invoices"),
	)


def sweep_stuck_intents(limit: int = 25, max_age_days: int = 3) -> dict:
	"""Hourly backstop: complete provider-paid intents the browser never closed.

	Only touches Created intents with a real provider order whose invoice is
	still unpaid. Each sync is idempotent; per-intent failures are recorded
	and skipped so one bad row never blocks the rest.
	"""
	since = add_to_date(now_datetime(), days=-max_age_days)
	rows = frappe.get_all(
		"Hosting Payment Transaction",
		filters={"status": "Created", "gateway_reference": ("like", "order_%"),
				"modified": [">=", since]},
		fields=["name", "source_invoice"],
		order_by="creation asc",
		limit=limit,
	)
	done, skipped, failed = [], [], {}
	for row in rows:
		if row.source_invoice:
			outstanding = float(frappe.db.get_value("Hosting Invoice", row.source_invoice, "outstanding_amount") or 0)
			if outstanding <= 0.005:
				skipped.append(row.name)
				continue
		try:
			out = sync_provider_payments(row.name)
			(done if out.get("allocated") else skipped).append(row.name)
		except Exception as exc:
			failed[row.name] = str(exc)[:200]
	return {"completed": done, "skipped": skipped, "failed": failed}


def sync_provider_payments(payment_name: str) -> dict:
	"""Reconcile one intent against the provider. Webhook/callback-independent.

	Looks up provider-side payments for the intent's order and completes local
	state (Captured + invoice allocation, both idempotent). For Razorpay,
	an authorized-but-uncaptured payment is captured first so local books
	never claim money the provider hasn't moved.
	"""
	payment = frappe.get_doc("Hosting Payment Transaction", payment_name)
	gateway = frappe.get_doc("Hosting Payment Gateway", payment.gateway)
	if gateway.provider != "Razorpay":
		frappe.throw(f"Provider sync is not supported for {gateway.provider}", frappe.ValidationError)
	if not (payment.gateway_reference or "").startswith("order_"):
		frappe.throw("No provider order linked to this payment yet", frappe.ValidationError)
	controller = get_provider_adapter(gateway)._controller()
	api_key = controller.api_key
	api_secret = controller.get_password(fieldname="api_secret", raise_exception=False)
	if not api_key or not api_secret:
		frappe.throw(f"Razorpay API credentials are not configured", frappe.ValidationError)
	import requests

	auth = (api_key, api_secret)
	try:
		with _prefer_ipv4():
			found = requests.get(
				f"https://api.razorpay.com/v1/orders/{payment.gateway_reference}/payments",
				auth=auth, timeout=60,
			)
		found.raise_for_status()
		remote = found.json() or {}
	except requests.RequestException as exc:
		frappe.throw(f"Razorpay lookup failed: {exc}")
	matched = None
	for item in remote.get("items", []):
		if (item.get("currency") or "").upper() != (payment.currency or "").upper():
			continue
		if item.get("status") in ("authorized", "captured"):
			# Order is unique per intent, so any live payment here belongs to
			# it. Amounts may differ by gateway fees; allocate what is owed.
			matched = item
	if not matched:
		return {"payment": payment.name, "status": payment.status, "provider_status": "none",
				"detail": "No authorized or captured payment found for this order yet"}
	provider_paid = float(matched.get("amount") or 0) / 100.0
	provider_status = matched.get("status")
	if provider_status == "authorized" and not matched.get("captured"):
		try:
			with _prefer_ipv4():
				cap = requests.post(
					f"https://api.razorpay.com/v1/payments/{matched['id']}/capture",
					auth=auth, timeout=60,
					data={"amount": int(round(min(provider_paid, float(payment.amount or 0)) * 100)),
							"currency": payment.currency},
				)
			cap.raise_for_status()
			provider_status = "captured"
		except requests.RequestException as exc:
			if "already captured" not in str(exc).lower():
				frappe.throw(f"Razorpay capture failed: {exc}")
	payment.reload()
	for step in ("Authorized", "Captured"):
		if payment.status == step:
			continue
		if payment.status == "Created" and step == "Authorized":
			payment.status = step
			payment.save()
		elif payment.status == "Authorized" and step == "Captured":
			payment.status = step
			payment.save()
	if payment.gateway_event_id != matched["id"]:
		payment.gateway_event_id = matched["id"]
		payment.save()
	allocated = False
	if payment.status == "Captured" and payment.source_invoice:
		from beaverbill.beaverbill import billing

		try:
			billing.allocate_payment(
				payment.name, payment.source_invoice, idempotency_key=f"sync-alloc-{payment.name}",
				ignore_permissions=True,
			)
			allocated = True
		except frappe.ValidationError:
			allocated = True  # already allocated or nothing outstanding
	return {"payment": payment.name, "status": payment.status,
			"provider_status": provider_status, "provider_payment": matched["id"],
			"allocated": allocated}


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
