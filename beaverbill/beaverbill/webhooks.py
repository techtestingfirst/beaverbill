"""Phase 5 webhook intake: verify, validate, store, apply in order, replay.

Duplicates return the stored event without new transitions. Out-of-order
delivery walks the payment through each intermediate state. Capture,
refund, and chargeback stay separate states with separate records.
"""

import hashlib
import hmac
import json

import frappe
from frappe.utils import today

from beaverbill.beaverbill import billing
from beaverbill.beaverbill.gateways import _gateway, target_status_for

ORDERED = ["Created", "Authorized", "Captured"]


class SchemaError(Exception):
	pass


def verify_signature(secret: str | None, raw_body: str, signature: str | None) -> bool:
	if not secret or not signature:
		return False
	sent = signature.removeprefix("sha256=").strip()
	calc = hmac.new(secret.encode(), raw_body.encode(), hashlib.sha256).hexdigest()
	return hmac.compare_digest(calc, sent)


def _parse_body(raw_body: str) -> dict:
	try:
		body = json.loads(raw_body)
	except ValueError as exc:
		raise SchemaError(f"Body is not JSON: {exc}") from exc
	if not isinstance(body, dict):
		raise SchemaError("Body must be a JSON object")
	return body


def validate_schema(body: dict) -> dict:
	event_id = body.get("id")
	event_type = body.get("type") or body.get("event")
	if not event_id or not isinstance(event_id, str):
		raise SchemaError("Event needs a string id")
	if not event_type or not isinstance(event_type, str):
		raise SchemaError("Event needs a string type")
	return {"event_id": event_id, "event_type": event_type}


def _normalize(provider: str, body: dict) -> dict:
	"""Pull the payment reference, amount, and currency from a payload."""
	if provider == "Razorpay":
		return _normalize_razorpay(body)
	if provider == "Stripe":
		return _normalize_stripe(body)
	return {
		"payment_reference": body.get("payment_reference"),
		"amount": body.get("amount"),
		"currency": body.get("currency"),
	}


def _normalize_razorpay(body: dict) -> dict:
	entity = ((body.get("payload") or {}).get("payment") or {}).get("entity") or {}
	refund = ((body.get("payload") or {}).get("refund") or {}).get("entity") or {}
	node = entity or refund
	amount = float(node["amount"]) / 100.0 if node.get("amount") is not None else None
	return {
		"payment_reference": entity.get("order_id") or entity.get("id") or refund.get("payment_id"),
		"amount": amount if not refund else float(refund.get("amount", 0)) / 100.0,
		"currency": node.get("currency"),
	}


def _normalize_stripe(body: dict) -> dict:
	obj = (body.get("data") or {}).get("object") or {}
	meta = obj.get("metadata") or {}
	amount = obj.get("amount_received", obj.get("amount"))
	return {
		"payment_reference": meta.get("beaverbill_payment") or obj.get("payment_intent") or obj.get("id"),
		"amount": float(amount) / 100.0 if amount is not None else None,
		"currency": (obj.get("currency") or "").upper() or None,
	}


def _find_payment(gateway_name, reference):
	if not reference:
		return None
	for field in ("gateway_reference", "name"):
		name = frappe.db.get_value(
			"Hosting Payment Transaction", {field: reference, "gateway": gateway_name}, "name"
		)
		if name:
			return frappe.get_doc("Hosting Payment Transaction", name)
	return None


def receive_webhook(gateway_name: str, raw_body: str, signature: str | None = None):
	"""Run the full intake pipeline. Idempotent per gateway event id."""
	gateway = _gateway(gateway_name)
	body = _parse_body(raw_body)
	meta = validate_schema(body)
	payload_hash = hashlib.sha256(raw_body.encode()).hexdigest()
	seen = frappe.db.get_value("Hosting Payment Event", {"event_id": meta["event_id"]}, "name")
	if seen:
		doc = frappe.get_doc("Hosting Payment Event", seen)
		if doc.gateway != gateway_name:
			frappe.throw("Event id already belongs to another gateway", frappe.ValidationError)
		doc.attempts = int(doc.attempts or 0) + 1
		doc.save(ignore_permissions=True)
		return doc
	event = frappe.get_doc(
		{
			"doctype": "Hosting Payment Event",
			"event_id": meta["event_id"],
			"gateway": gateway_name,
			"event_type": meta["event_type"],
			"payload_hash": payload_hash,
			"payload": raw_body[:10000],
			"signature_valid": 0,
			"status": "Received",
			"attempts": 0,
			"idempotency_key": f"evt-{meta['event_id']}"[:100],
		}
	).insert(ignore_permissions=True)
	# get_doc decrypts Password fields; get_value would return ciphertext.
	secret = frappe.get_doc("Hosting Payment Gateway", gateway_name).get_password("webhook_secret")
	if not verify_signature(secret, raw_body, signature):
		event.signature_valid = 0
		event.status = "Failed"
		event.last_error = "Invalid webhook signature"
		event.save(ignore_permissions=True)
		frappe.throw("Invalid webhook signature", frappe.PermissionError)
	event.signature_valid = 1
	event.status = "Validated"
	event.save(ignore_permissions=True)
	_apply_event(event)
	return event


def _apply_event(event):
	"""Map one validated event onto its payment. Raises on mismatch."""
	gateway = frappe.get_doc("Hosting Payment Gateway", event.gateway)
	target = target_status_for(gateway.provider, event.event_type)
	if target is None:
		event.status = "Ignored"
		event.last_error = f"No mapping for {event.event_type}"
		event.save(ignore_permissions=True)
		return event
	body = _parse_body(event.payload or "{}")
	ref = _normalize(gateway.provider, body)
	payment = _find_payment(event.gateway, ref.get("payment_reference"))
	if payment is None:
		event.status = "Failed"
		event.last_error = f"Unknown payment {ref.get('payment_reference')}"
		event.save(ignore_permissions=True)
		frappe.throw(event.last_error, frappe.ValidationError)
	if ref.get("amount") is not None and target in ("Captured", "Authorized"):
		if abs(float(ref["amount"]) - float(payment.amount or 0)) > 0.01:
			event.status = "Failed"
			event.last_error = f"Amount {ref['amount']} differs from payment {payment.amount}"
			event.save(ignore_permissions=True)
			frappe.throw(event.last_error, frappe.ValidationError)
	event.payment = payment.name
	if target in ORDERED:
		_walk_to(payment, target)
	elif target == "Failed":
		payment.status = "Failed"
		payment.last_error = f"Gateway reported {event.event_type}"
		payment.save()
	elif target in ("Refunded", "Chargeback"):
		_apply_money_out(event, payment, ref, target)
	payment.gateway_event_id = event.event_id
	payment.save()
	if target == "Captured" and payment.source_invoice:
		try:
			billing.allocate_payment(
				payment.name, payment.source_invoice, idempotency_key=f"wh-alloc-{event.event_id}"
			)
		except frappe.ValidationError:
			pass
	event.attempts = int(event.attempts or 0) + 1
	event.status = "Processed"
	event.save(ignore_permissions=True)
	return event


def _walk_to(payment, target):
	"""Step a payment forward one legal transition at a time."""
	current = payment.status
	if current == target:
		return payment
	if current not in ORDERED or target not in ORDERED:
		frappe.throw(f"Payment cannot move from {current} to {target}", frappe.ValidationError)
	if ORDERED.index(target) < ORDERED.index(current):
		frappe.throw(f"Payment cannot move back from {current} to {target}", frappe.ValidationError)
	for step in ORDERED[ORDERED.index(current) + 1 : ORDERED.index(target) + 1]:
		payment.status = step
		payment.save()
	return payment


def _apply_money_out(event, payment, ref, target):
	amount = float(ref.get("amount") or payment.amount or 0)
	if target == "Refunded":
		billing.process_refund(
			payment.customer, amount, payment=payment.name, reason=f"Gateway event {event.event_id}",
			idempotency_key=f"wh-{event.event_id}",
		)
		payment.reload()
	else:
		chargeback = frappe.get_doc(
			{
				"doctype": "Hosting Refund",
				"customer": payment.customer,
				"payment": payment.name,
				"refund_date": today(),
				"amount": amount,
				"status": "Chargeback",
				"reason": f"Gateway event {event.event_id}",
				"idempotency_key": f"wh-{event.event_id}",
			}
		).insert(ignore_permissions=True)
		billing.post_ledger(
			payment.customer, amount, "Credit", f"Chargeback {chargeback.name}",
			"Hosting Refund", chargeback.name, idempotency_key=f"wh-ledger-{event.event_id}",
		)
		payment.status = "Chargeback"
		payment.save()


@frappe.whitelist(allow_guest=True)
def gateway_webhook(gateway: str | None = None):
	"""Public webhook URL: /api/method/beaverbill.beaverbill.webhooks.gateway_webhook."""
	name = gateway or frappe.form_dict.get("gateway")
	raw = frappe.request.data.decode() if isinstance(frappe.request.data, bytes) else (frappe.request.data or "")
	signature = frappe.get_request_header("X-Webhook-Signature") or frappe.form_dict.get("signature")
	event = receive_webhook(name, raw, signature)
	return {"event": event.name, "status": event.status}


def _require_staff():
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles & {"System Manager", "Hosting Admin"}:
		frappe.throw("Only billing staff may run this action", frappe.PermissionError)


@frappe.whitelist()
def replay_payment_event(event_name: str) -> str:
	"""Staff action: re-apply a failed or stuck event. Processed events stay put."""
	_require_staff()
	event = frappe.get_doc("Hosting Payment Event", event_name)
	if event.status == "Processed":
		return event.name
	if event.status not in ("Failed", "Received", "Validated"):
		frappe.throw(f"Event {event.status} cannot be replayed", frappe.ValidationError)
	event.status = "Validated"
	event.last_error = None
	event.save()
	event.reload()
	_apply_event(event)
	return event.name
