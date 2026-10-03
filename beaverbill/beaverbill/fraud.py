"""Fraud screening: allow / hold / reject orders before payment.

Heuristics stay deterministic and offline: disposable email domains,
form manual-review flag, and high-value first orders. Providers
MaxMind/FraudLabs plug in later via the same decision shape.
"""

import frappe

DISPOSABLE = {"mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com"}
HIGH_VALUE_THRESHOLD = 500.0


def _request_ip() -> str | None:
    try:
        return frappe.local.request_ip
    except Exception:
        return None


def screen_order(order_name: str, provider: str = "Simulated") -> dict:
    """Score one Draft order. Writes a screening log. Never raises on provider failure."""
    order = frappe.get_doc("Hosting Order", order_name)
    signals: list[str] = []
    score = 0.0

    email = (order.customer or "").strip().lower()
    domain = email.split("@")[-1] if "@" in email else ""
    if domain in DISPOSABLE:
        signals.append(f"disposable email {domain}")
        score += 60.0

    total = float(order.total_amount or 0)
    if total >= HIGH_VALUE_THRESHOLD:
        signals.append(f"high value {total}")
        score += 30.0

    if order.get("order_form"):
        manual = frappe.db.get_value("Hosting Order Form", order.order_form, "require_manual_review")
        if manual:
            signals.append("form requires manual review")
            score = max(score, 50.0)

    ip = _request_ip()
    if ip:
        signals.append(f"ip {ip}")

    if score >= 80:
        decision = "reject"
    elif score >= 40:
        decision = "hold"
    elif order.get("order_form") and frappe.db.get_value(
        "Hosting Order Form", order.order_form, "require_manual_review"
    ):
        decision = "manual"
    else:
        decision = "allow"

    frappe.get_doc(
        {
            "doctype": "Hosting Fraud Screening",
            "order": order.name,
            "provider": provider,
            "decision": decision,
            "score": score,
            "signals": "; ".join(signals)[:1000],
        }
    ).insert(ignore_permissions=True)
    return {"order": order.name, "decision": decision, "score": score, "signals": signals}
