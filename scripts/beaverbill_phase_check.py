"""Phase gate checks for Beaver Bill.

Reads the current phase from progress/phase-status.json and runs the
checks required by plan.md. Prints one JSON report to stdout.

Usage:
    python3 scripts/beaverbill_phase_check.py <phase-id> [--root DIR]

Exit code 0 when every required check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

STATUS_FILE = "progress/phase-status.json"
PROCESS_FILE = "process.md"
AUDIT_DOC = "docs/phase-0-audit.md"
EVIDENCE_DIR = "docs/evidence"

REQUIRED_FILES = [
    "AGENTS.md",
    "progress/phase-status.json",
    "scripts/beaverbill_phase_check.py",
    "scripts/mark_phase_complete.py",
    "scripts/run_phase_gate.sh",
    ".githooks/pre-commit",
]

MARKERS = [
    "<!-- AUTO-PROGRESS-START -->",
    "<!-- AUTO-PROGRESS-END -->",
    "<!-- AUTO-COMPLETION-LOG-START -->",
    "<!-- AUTO-COMPLETION-LOG-END -->",
]

# Code patterns that prove a real ERPNext dependency. Plain mentions in
# markdown docs are allowed because the docs describe the prohibition.
ERPNEXT_PATTERNS = [
    re.compile(r"^\s*import\s+erpnext\b", re.MULTILINE),
    re.compile(r"^\s*from\s+erpnext\b", re.MULTILINE),
    re.compile(r"""['"]erpnext['"]\s*:\s*["'][^"']*["']"""),
    re.compile(r"required_apps\s*=\s*\[[^\]]*erpnext", re.DOTALL),
]

SCAN_EXTENSIONS = (".py", ".js", ".ts", ".vue", ".json", ".txt", ".toml", ".cfg")
SCAN_EXCLUDE_DIRS = {".git", "node_modules", "__pycache__", ".aider.tags.cache.v4"}

VALID_STATUSES = {
    "not_started",
    "in_progress",
    "blocked",
    "implemented",
    "completed",
    "deferred",
    "deprecated",
}


class Check:
    """One named gate check with a pass flag and a detail message."""

    def __init__(self, name, required=True):
        self.name = name
        self.required = required
        self.passed = False
        self.detail = ""

    def to_dict(self):
        return {
            "name": self.name,
            "required": self.required,
            "passed": self.passed,
            "detail": self.detail,
        }


def repo_path(root, *parts):
    return os.path.join(root, *parts)


def run_git(root, *args):
    try:
        out = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def check_progress_scripts(root):
    check = Check("progress_scripts")
    missing = [f for f in REQUIRED_FILES if not os.path.isfile(repo_path(root, f))]
    not_exec = [
        f
        for f in [
            "scripts/beaverbill_phase_check.py",
            "scripts/mark_phase_complete.py",
            "scripts/run_phase_gate.sh",
            ".githooks/pre-commit",
        ]
        if os.path.isfile(repo_path(root, f))
        and not os.access(repo_path(root, f), os.X_OK)
    ]
    try:
        with open(repo_path(root, PROCESS_FILE), encoding="utf-8") as fh:
            process_text = fh.read()
        missing_markers = [m for m in MARKERS if m not in process_text]
    except OSError:
        missing_markers = MARKERS
    try:
        with open(repo_path(root, STATUS_FILE), encoding="utf-8") as fh:
            status = json.load(fh)
        bad = [k for k, v in status.get("phases", {}).items() if v.get("status") not in VALID_STATUSES]
    except (OSError, ValueError) as exc:
        check.detail = f"phase-status.json unreadable: {exc}"
        return check
    problems = []
    if missing:
        problems.append(f"missing files: {', '.join(missing)}")
    if not_exec:
        problems.append(f"not executable: {', '.join(not_exec)}")
    if missing_markers:
        problems.append(f"markers absent from process.md: {len(missing_markers)}")
    if bad:
        problems.append(f"invalid statuses: {', '.join(bad)}")
    check.passed = not problems
    check.detail = "all progress files present and valid" if check.passed else "; ".join(problems)
    return check


def check_erpnext_scan(root):
    check = Check("erpnext_scan")
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SCAN_EXCLUDE_DIRS]
        for name in filenames:
            if not name.endswith(SCAN_EXTENSIONS):
                continue
            full = os.path.join(dirpath, name)
            try:
                with open(full, encoding="utf-8", errors="strict") as fh:
                    text = fh.read()
            except (OSError, UnicodeError):
                continue
            for pattern in ERPNEXT_PATTERNS:
                if pattern.search(text):
                    hits.append(os.path.relpath(full, root))
                    break
    check.passed = not hits
    check.detail = "no ERPNext imports or dependencies found" if check.passed else f"ERPNext references: {', '.join(hits)}"
    return check


def check_git_commit(root):
    check = Check("git_commit")
    sha = run_git(root, "rev-parse", "HEAD")
    check.passed = bool(sha and re.fullmatch(r"[0-9a-f]{40}", sha))
    check.detail = f"full commit SHA: {sha}" if check.passed else "no full Git commit SHA available"
    return check


def check_audit_doc(root):
    check = Check("audit_doc")
    path = repo_path(root, AUDIT_DOC)
    try:
        size = os.path.getsize(path)
    except OSError:
        check.detail = f"{AUDIT_DOC} is missing"
        return check
    if size < 500:
        check.detail = f"{AUDIT_DOC} is incomplete ({size} bytes)"
        return check
    check.passed = True
    check.detail = f"{AUDIT_DOC} exists ({size} bytes)"
    return check


def check_evidence(root):
    check = Check("evidence", required=False)
    base = repo_path(root, EVIDENCE_DIR)
    found = []
    if os.path.isdir(base):
        for dirpath, _, filenames in os.walk(base):
            found.extend(f for f in filenames if not f.startswith("."))
    check.passed = bool(found)
    check.detail = f"{len(found)} evidence files under {EVIDENCE_DIR}" if check.passed else f"no evidence files under {EVIDENCE_DIR}"
    return check


def candidate_pythons(root):
    """Pythons that may have frappe importable, best first."""
    seen = []
    for path in (
        sys.executable,
        os.path.join(root, "..", "..", "env", "bin", "python"),
        "/usr/bin/python3",
    ):
        full = os.path.normpath(path)
        if full not in seen:
            seen.append(full)
    return seen


def collect_with(python, root):
    try:
        return subprocess.run(
            [python, "-m", "pytest", "--collect-only", "-q", "beaverbill"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=root,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_tests(root):
    """Confirm the existing test files are still present and collectable."""
    check = Check("existing_tests")
    test_files = []
    for dirpath, dirnames, filenames in os.walk(repo_path(root, "beaverbill")):
        dirnames[:] = [d for d in dirnames if d not in SCAN_EXCLUDE_DIRS]
        test_files.extend(os.path.join(dirpath, f) for f in filenames if f.startswith("test_") and f.endswith(".py"))
    if not test_files:
        check.detail = "no test files found under beaverbill/"
        return check
    last_output = ""
    for python in candidate_pythons(root):
        out = collect_with(python, root)
        if out is None:
            last_output = f"{python} unavailable"
            continue
        if out.returncode == 0:
            check.passed = True
            check.detail = f"{len(test_files)} test files collect cleanly with {python}"
            return check
        last_output = (out.stdout + out.stderr).strip()[-500:]
    check.detail = f"pytest collection failed: {last_output}"
    return check


def sized_doc(root, relpath, minimum=500, name=None):
    check = Check(name or relpath)
    path = repo_path(root, relpath)
    try:
        size = os.path.getsize(path)
    except OSError:
        check.detail = f"{relpath} is missing"
        return check
    if size < minimum:
        check.detail = f"{relpath} is incomplete ({size} bytes)"
        return check
    check.passed = True
    check.detail = f"{relpath} exists ({size} bytes)"
    return check


def check_phase1_reports(root):
    check = Check("phase1_reports")
    wanted = [
        "beaverbill/beaverbill/report/ip_pool_exhaustion/ip_pool_exhaustion.json",
        "beaverbill/beaverbill/report/duplicate_ip_allocation/duplicate_ip_allocation.json",
    ]
    missing = [r for r in wanted if not os.path.isfile(repo_path(root, r))]
    check.passed = not missing
    check.detail = "both IPAM reports present" if check.passed else f"missing: {', '.join(missing)}"
    return check


def check_phase3_models(root):
    check = Check("phase3_models")
    wanted = [
        "beaverbill/beaverbill/doctype/hosting_customer/hosting_customer.json",
        "beaverbill/beaverbill/doctype/hosting_customer_contact/hosting_customer_contact.json",
        "beaverbill/beaverbill/doctype/hosting_customer_group/hosting_customer_group.json",
        "beaverbill/beaverbill/doctype/hosting_service/hosting_service.json",
        "beaverbill/beaverbill/backfill_services.py",
        "beaverbill/beaverbill/permissions.py",
    ]
    missing = [r for r in wanted if not os.path.isfile(repo_path(root, r))]
    try:
        with open(repo_path(root, "beaverbill", "hooks.py"), encoding="utf-8") as fh:
            hooks = fh.read()
        wired = "hosting_service_query_conditions" in hooks and "check_service_ownership" in hooks
    except OSError:
        wired = False
    problems = []
    if missing:
        problems.append(f"missing: {', '.join(missing)}")
    if not wired:
        problems.append("ownership hooks not wired in hooks.py")
    check.passed = not problems
    check.detail = "customer/service models and hooks present" if check.passed else "; ".join(problems)
    return check


def check_phase2_models(root):
    check = Check("phase2_models")
    wanted = [
        "beaverbill/beaverbill/doctype/hosting_product_price/hosting_product_price.json",
        "beaverbill/beaverbill/doctype/hosting_tax_rule/hosting_tax_rule.json",
        "beaverbill/beaverbill/doctype/hosting_customer_tax_profile/hosting_customer_tax_profile.json",
        "beaverbill/beaverbill/doctype/hosting_currency_exchange_rate/hosting_currency_exchange_rate.json",
        "beaverbill/beaverbill/doctype/hosting_promo_redemption/hosting_promo_redemption.json",
        "beaverbill/beaverbill/pricing.py",
    ]
    missing = [r for r in wanted if not os.path.isfile(repo_path(root, r))]
    try:
        with open(repo_path(root, "beaverbill", "patches.txt"), encoding="utf-8") as fh:
            has_patch = "phase2_seed_product_prices" in fh.read()
    except OSError:
        has_patch = False
    problems = []
    if missing:
        problems.append(f"missing: {', '.join(missing)}")
    if not has_patch:
        problems.append("phase2 seed patch not registered")
    check.passed = not problems
    check.detail = "catalog models and seed patch present" if check.passed else "; ".join(problems)
    return check


def check_phase4_models(root):
    check = Check("phase4_models")
    wanted = [
        "beaverbill/beaverbill/doctype/hosting_invoice_item/hosting_invoice_item.json",
        "beaverbill/beaverbill/doctype/hosting_payment_transaction/hosting_payment_transaction.json",
        "beaverbill/beaverbill/doctype/hosting_payment_allocation/hosting_payment_allocation.json",
        "beaverbill/beaverbill/doctype/hosting_refund/hosting_refund.json",
        "beaverbill/beaverbill/doctype/hosting_credit_note/hosting_credit_note.json",
        "beaverbill/beaverbill/doctype/hosting_debit_note/hosting_debit_note.json",
        "beaverbill/beaverbill/billing.py",
        "beaverbill/beaverbill/tests/test_billing_ledger.py",
        "beaverbill/beaverbill/report/invoice_outstanding/invoice_outstanding.json",
        "beaverbill/beaverbill/report/credit_ledger_mismatch/credit_ledger_mismatch.json",
    ]
    missing = [r for r in wanted if not os.path.isfile(repo_path(root, r))]
    problems = []
    if missing:
        problems.append(f"missing: {', '.join(missing)}")
    try:
        with open(repo_path(root, "beaverbill", "beaverbill", "doctype", "hosting_invoice", "hosting_invoice.json"), encoding="utf-8") as fh:
            invoice = json.load(fh)
        fields = {f.get("fieldname") for f in invoice.get("fields", [])}
        options = next((f.get("options", "") for f in invoice.get("fields", []) if f.get("fieldname") == "status"), "")
        if "items" not in fields or "paid_amount" not in fields:
            problems.append("Hosting Invoice lacks ledger fields")
        for state in ("Issued", "Partially Paid", "Written Off"):
            if state not in options:
                problems.append(f"Hosting Invoice status lacks {state}")
    except (OSError, ValueError) as exc:
        problems.append(f"invoice schema unreadable: {exc}")
    check.passed = not problems
    check.detail = "billing models and invoice ledger present" if check.passed else "; ".join(problems)
    return check


def check_phase5_models(root):
    check = Check("phase5_models")
    wanted = [
        "beaverbill/beaverbill/doctype/hosting_payment_gateway/hosting_payment_gateway.json",
        "beaverbill/beaverbill/doctype/hosting_payment_method/hosting_payment_method.json",
        "beaverbill/beaverbill/doctype/hosting_payment_event/hosting_payment_event.json",
        "beaverbill/beaverbill/gateways.py",
        "beaverbill/beaverbill/webhooks.py",
        "beaverbill/beaverbill/tests/test_gateway_webhooks.py",
        "beaverbill/beaverbill/report/gateway_reconciliation/gateway_reconciliation.json",
        "beaverbill/beaverbill/report/unprocessed_webhooks/unprocessed_webhooks.json",
    ]
    missing = [r for r in wanted if not os.path.isfile(repo_path(root, r))]
    problems = []
    if missing:
        problems.append(f"missing: {', '.join(missing)}")
    try:
        with open(repo_path(root, "beaverbill", "beaverbill", "doctype", "hosting_payment_method", "hosting_payment_method.json"), encoding="utf-8") as fh:
            method = json.load(fh)
        fields = {f.get("fieldname") for f in method.get("fields", [])}
        if "token_reference" not in fields:
            problems.append("Hosting Payment Method lacks token_reference")
        if {"card_number", "pan", "cvv", "card_cvv"} & fields:
            problems.append("Hosting Payment Method must not store card data")
    except (OSError, ValueError) as exc:
        problems.append(f"payment method schema unreadable: {exc}")
    check.passed = not problems
    check.detail = "gateway models and webhook pipeline present" if check.passed else "; ".join(problems)
    return check


def check_phase1_patch(root):
    check = Check("phase1_patch")
    patches_file = repo_path(root, "beaverbill", "patches.txt")
    try:
        with open(patches_file, encoding="utf-8") as fh:
            entries = [line.strip() for line in fh if line.strip().startswith("beaverbill.patches.")]
    except OSError:
        check.detail = "beaverbill/patches.txt unreadable"
        return check
    missing = [
        e for e in entries if not os.path.isfile(repo_path(root, *e.split(".")) + ".py")
    ]
    if not entries:
        check.detail = "no patch registered in beaverbill/patches.txt"
    elif missing:
        check.detail = f"patch file missing: {', '.join(missing)}"
    else:
        check.passed = True
        check.detail = f"{len(entries)} registered patch(es) present"
    return check


PHASE_CHECKS = {
    "phase-0": ("progress_scripts", "erpnext_scan", "git_commit", "audit_doc", "existing_tests"),
    "phase-1": (
        "progress_scripts",
        "erpnext_scan",
        "git_commit",
        "existing_tests",
        "phase1_doc",
        "phase1_reports",
        "phase1_patch",
    ),
    "phase-2": (
        "progress_scripts",
        "erpnext_scan",
        "git_commit",
        "existing_tests",
        "phase2_doc",
        "phase2_models",
    ),
    "phase-3": (
        "progress_scripts",
        "erpnext_scan",
        "git_commit",
        "existing_tests",
        "phase3_doc",
        "phase3_models",
    ),
    "phase-4": (
        "progress_scripts",
        "erpnext_scan",
        "git_commit",
        "existing_tests",
        "phase4_doc",
        "phase4_models",
    ),
    "phase-5": (
        "progress_scripts",
        "erpnext_scan",
        "git_commit",
        "existing_tests",
        "phase5_doc",
        "phase5_models",
    ),
}

ALL_CHECKS = {
    "progress_scripts": check_progress_scripts,
    "erpnext_scan": check_erpnext_scan,
    "git_commit": check_git_commit,
    "audit_doc": check_audit_doc,
    "evidence": check_evidence,
    "existing_tests": check_tests,
    "phase1_doc": lambda root: sized_doc(root, "docs/phase-1-hardening.md", name="phase1_doc"),
    "phase2_doc": lambda root: sized_doc(root, "docs/phase-2-catalog.md", name="phase2_doc"),
    "phase2_models": check_phase2_models,
    "phase3_doc": lambda root: sized_doc(root, "docs/phase-3-customer.md", name="phase3_doc"),
    "phase3_models": check_phase3_models,
    "phase4_doc": lambda root: sized_doc(root, "docs/phase-4-billing.md", name="phase4_doc"),
    "phase4_models": check_phase4_models,
    "phase5_doc": lambda root: sized_doc(root, "docs/phase-5-gateway.md", name="phase5_doc"),
    "phase5_models": check_phase5_models,
    "phase1_reports": check_phase1_reports,
    "phase1_patch": check_phase1_patch,
}


def run_phase(phase_id, root):
    required = set(PHASE_CHECKS.get(phase_id, ("progress_scripts", "erpnext_scan", "git_commit")))
    results = []
    for name, func in ALL_CHECKS.items():
        if name in required or name == "evidence":
            check = func(root)
            check.required = name in required
            results.append(check)
    passed = all(c.passed for c in results if c.required)
    return {
        "phase": phase_id,
        "passed": passed,
        "checks": [c.to_dict() for c in results],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run Beaver Bill phase gate checks.")
    parser.add_argument("phase", help="phase id, for example phase-0")
    parser.add_argument("--root", default=os.getcwd(), help="repository root")
    args = parser.parse_args(argv)
    report = run_phase(args.phase, args.root)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
