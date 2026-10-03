"""Tax helpers: Tax ID validation stub, reverse charge, company context.

Live VIES/HMRC calls plug in later behind validate_tax_id. The stub
checks format per country prefix and marks obviously bad IDs invalid,
so checkout can proceed offline and real verification tightens later.
"""

import re

import frappe

from beaverbill.beaverbill import settings as bb_settings

EU_COUNTRIES = {
    "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia",
    "Denmark", "Estonia", "Finland", "France", "Germany", "Greece",
    "Hungary", "Ireland", "Italy", "Latvia", "Lithuania", "Luxembourg",
    "Malta", "Netherlands", "Poland", "Portugal", "Romania", "Slovakia",
    "Slovenia", "Spain", "Sweden",
}

VAT_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{6,14}$")


def company_country() -> str:
    return (bb_settings.get_str("company_country", "") or "").strip()


def tax_enabled() -> bool:
    return bb_settings.get_int("tax_enabled", 1) == 1


def validate_tax_id(tax_id: str, country: str) -> dict:
    """Format-check a VAT/Tax ID. Returns validated flag + source stub."""
    clean = re.sub(r"[\s\-.]", "", (tax_id or "").upper())
    if not clean:
        frappe.throw("Tax ID is required", frappe.ValidationError)
    if country in EU_COUNTRIES or country == "United Kingdom":
        valid = bool(VAT_RE.match(clean))
        source = "VIES-stub" if country in EU_COUNTRIES else "HMRC-stub"
        return {"tax_id": clean, "validated": valid, "source": source}
    return {"tax_id": clean, "validated": len(clean) >= 4, "source": "format"}


def is_reverse_charge(profile_country: str, tax_id_validated: bool) -> bool:
    """EU cross-border B2B zero-rate: valid VAT ID + different country than company."""
    comp = company_country()
    if not comp or comp not in EU_COUNTRIES:
        return False
    if not profile_country or profile_country not in EU_COUNTRIES:
        return False
    return bool(tax_id_validated) and profile_country != comp
