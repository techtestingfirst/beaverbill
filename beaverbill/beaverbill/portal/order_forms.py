"""Portal: order forms plus domain-first availability checks."""

import frappe

from beaverbill.beaverbill import domains as domain_engine
from beaverbill.beaverbill.portal.guard import portal_endpoint


@frappe.whitelist()
@portal_endpoint("portal.list_order_forms", limit=60)
def list_order_forms() -> dict:
    """Active order forms (template + type + rules)."""
    rows = frappe.get_all(
        "Hosting Order Form",
        filters={"is_active": 1},
        fields=[
            "name",
            "form_name",
            "template",
            "form_type",
            "require_tos",
            "require_recurring_consent",
            "require_captcha",
            "allow_coupon",
            "require_manual_review",
        ],
        order_by="form_name asc",
    )
    return {"forms": rows}


@frappe.whitelist()
@portal_endpoint("portal.get_order_form", limit=60)
def get_order_form(form: str) -> dict:
    """One order form with TOS text and product-group scope."""
    doc = frappe.get_doc("Hosting Order Form", form)
    if not doc.is_active:
        frappe.throw(f"Order form {form} is not active", frappe.ValidationError)
    return {
        "name": doc.name,
        "form_name": doc.form_name,
        "template": doc.template,
        "form_type": doc.form_type,
        "product_groups": doc.product_groups,
        "require_tos": int(doc.require_tos or 0),
        "tos_text": doc.tos_text,
        "require_recurring_consent": int(doc.require_recurring_consent or 0),
        "require_captcha": int(doc.require_captcha or 0),
        "allow_coupon": int(doc.allow_coupon or 0),
        "require_manual_review": int(doc.require_manual_review or 0),
    }


@frappe.whitelist()
@portal_endpoint("portal.check_domain", limit=60)
def check_domain(domain: str) -> dict:
    """Live registrar availability check for the order-form domain step."""
    name = domain_engine.normalize_domain(domain)
    driver = domain_engine.get_registrar_driver()
    try:
        result = driver.check_availability(name)
    except Exception as exc:
        frappe.throw(f"Availability check failed: {exc}", frappe.ValidationError)
        result = {}
    taken = frappe.db.exists("Hosting Domain", {"domain_name": name})
    return {"domain": name, "available": bool(result.get("available")) and not taken}
