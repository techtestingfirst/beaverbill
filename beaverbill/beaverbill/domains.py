"""Phase 9 domain engine: registration, transfer, DNS, renewal, expiry.

Registrar calls route through a versioned adapter. The default
Simulated driver keeps legacy-style dict returns; failures are
classified with the Phase 8 taxonomy (reused ProvisioningError).
"""

import re
import uuid

import frappe
from frappe.utils import add_days, add_months, add_years, date_diff, getdate, now_datetime, today

from beaverbill.beaverbill import billing
from beaverbill.beaverbill.notifications import billable_customer, notify, require_staff
from beaverbill.beaverbill.provisioning_drivers import ProvisioningError

REGISTRAR_CONTRACT_VERSION = "1.0"

DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.[a-z0-9-]{1,63})*\.[a-z]{2,}$")
RENEWAL_PRICE = 15.0
RENEWAL_CURRENCY = "USD"

REMINDER_STAGES = (30, 14, 7, 1)
AUTO_RENEW_WITHIN_DAYS = 7
GRACE_DAYS = 30
REDEMPTION_DAYS = 30

# Fault injection for tests: {"register": msg, "renew": msg, "transfer": msg, "nameservers": msg}
REGISTRAR_FAULTS: dict = {}


class BaseRegistrarDriver:
	contract_version = REGISTRAR_CONTRACT_VERSION

	def __init__(self, account_name=None):
		self.account_name = account_name

	def check_availability(self, domain_name):
		raise NotImplementedError()

	def register(self, domain_name, years=1, nameservers=None):
		raise NotImplementedError()

	def renew(self, domain_name, years=1):
		raise NotImplementedError()

	def transfer(self, domain_name, auth_code):
		raise NotImplementedError()

	def get_nameservers(self, domain_name):
		raise NotImplementedError()

	def set_nameservers(self, domain_name, nameservers):
		raise NotImplementedError()


class SimulatedRegistrarDriver(BaseRegistrarDriver):
	"""In-memory registrar stand-in. State lives in REGISTRY for the run."""

	REGISTRY: dict = {}

	def check_availability(self, domain_name):
		if REGISTRAR_FAULTS.get("check"):
			raise ProvisioningError(REGISTRAR_FAULTS["check"], error_type="transient")
		return {"available": domain_name not in self.REGISTRY}

	def register(self, domain_name, years=1, nameservers=None):
		if REGISTRAR_FAULTS.get("register"):
			raise ProvisioningError(REGISTRAR_FAULTS["register"], error_type="transient")
		if domain_name in self.REGISTRY:
			raise ProvisioningError(f"{domain_name} is already registered", error_type="permanent")
		self.REGISTRY[domain_name] = {
			"expiry": add_years(getdate(today()), years),
			"nameservers": list(nameservers or ["ns1.example.net", "ns2.example.net"]),
		}
		return {"status": "Success", "expiry": str(self.REGISTRY[domain_name]["expiry"])}

	def renew(self, domain_name, years=1):
		if REGISTRAR_FAULTS.get("renew"):
			raise ProvisioningError(REGISTRAR_FAULTS["renew"], error_type="transient")
		entry = self.REGISTRY.get(domain_name)
		if not entry:
			raise ProvisioningError(f"{domain_name} not found at registrar", error_type="permanent")
		entry["expiry"] = add_years(getdate(entry["expiry"]), years)
		return {"status": "Success", "expiry": str(entry["expiry"])}

	def transfer(self, domain_name, auth_code):
		if REGISTRAR_FAULTS.get("transfer"):
			raise ProvisioningError(REGISTRAR_FAULTS["transfer"], error_type="transient")
		if not auth_code:
			raise ProvisioningError("Auth code is required for transfer", error_type="permanent")
		self.REGISTRY[domain_name] = {
			"expiry": add_years(getdate(today()), 1),
			"nameservers": ["ns1.example.net", "ns2.example.net"],
		}
		return {"status": "Success", "expiry": str(self.REGISTRY[domain_name]["expiry"])}

	def get_nameservers(self, domain_name):
		entry = self.REGISTRY.get(domain_name)
		if not entry:
			raise ProvisioningError(f"{domain_name} not found at registrar", error_type="permanent")
		return {"status": "Success", "nameservers": entry["nameservers"]}

	def set_nameservers(self, domain_name, nameservers):
		if REGISTRAR_FAULTS.get("nameservers"):
			raise ProvisioningError(REGISTRAR_FAULTS["nameservers"], error_type="transient")
		entry = self.REGISTRY.get(domain_name)
		if not entry:
			raise ProvisioningError(f"{domain_name} not found at registrar", error_type="permanent")
		if len(nameservers or []) < 2:
			raise ProvisioningError("At least two nameservers are required", error_type="permanent")
		entry["nameservers"] = list(nameservers)
		return {"status": "Success", "nameservers": entry["nameservers"]}


def get_registrar_driver(account_name=None):
	if account_name:
		provider = frappe.db.get_value("Domain Registrar Account", account_name, "registrar")
		active = frappe.db.get_value("Domain Registrar Account", account_name, "is_active")
		if active == 0:
			raise ProvisioningError(f"Registrar account {account_name} is disabled", error_type="permanent")
		if provider and provider not in ("Simulated", "Custom"):
			raise ProvisioningError(f"Unsupported registrar provider: {provider}", error_type="permanent")
	return SimulatedRegistrarDriver(account_name)


def normalize_domain(name: str) -> str:
	clean = (name or "").strip().lower()
	if not DOMAIN_RE.match(clean):
		frappe.throw(f"Invalid domain name: {name}", frappe.ValidationError)
	return clean


def _default_registrar_account():
	name = frappe.db.get_value("Domain Registrar Account", {"is_active": 1}, "name")
	if name:
		return name
	return frappe.get_doc(
		{"doctype": "Domain Registrar Account", "registrar_name": "Default Simulated", "registrar": "Simulated"}
	).insert().name


@frappe.whitelist()
def register_domain(customer: str, domain_name: str, registrar_account: str | None = None,
					service: str | None = None, years: int = 1, idempotency_key: str | None = None) -> dict:
	"""Register a domain; idempotent by key, duplicates refused."""
	name = normalize_domain(domain_name)
	key = idempotency_key or f"domain-reg-{name}"
	existing = frappe.db.get_value("Hosting Domain", {"idempotency_key": key}, "name")
	if existing:
		doc = frappe.get_doc("Hosting Domain", existing)
		return {"domain": doc.name, "status": doc.status, "duplicate_request": True}
	if frappe.db.exists("Hosting Domain", {"domain_name": name}):
		frappe.throw(f"Domain {name} is already managed by Beaver Bill", frappe.ValidationError)
	account = registrar_account or _default_registrar_account()
	doc = frappe.get_doc(
		{
			"doctype": "Hosting Domain",
			"domain_name": name,
			"customer": customer,
			"service": service,
			"registrar_account": account,
			"status": "Pending Registration",
			"idempotency_key": key,
			"auto_renew": 1,
		}
	).insert()
	try:
		driver = get_registrar_driver(account)
		available = driver.check_availability(name).get("available", True)
		if not available:
			raise ProvisioningError(f"{name} is unavailable for registration", error_type="permanent")
		result = driver.register(name, years=years)
	except ProvisioningError as exc:
		# Registrar failure recovery: park as Cancelled with the reason;
		# staff retry via retry_domain_registration (same idempotency key).
		doc.status = "Cancelled"
		doc.failure_reason = f"Registration failed ({exc.error_type}): {exc}"[:1000]
		doc.save(ignore_permissions=True)
		notify(customer, f"Domain {name} registration failed",
			   f"{exc} Your domain was not charged.", "Hosting Domain", doc.name)
		return {"domain": doc.name, "status": doc.status, "error": str(exc)}
	doc.registration_date = today()
	doc.expiry_date = getdate(result.get("expiry")) if result.get("expiry") else add_years(getdate(today()), years)
	doc.status = "Active"
	doc.nameservers = "\n".join((result.get("nameservers") or ["ns1.example.net", "ns2.example.net"]))
	doc.failure_reason = None
	doc.save(ignore_permissions=True)
	notify(customer, f"Domain {name} registered", f"Your domain is active until {doc.expiry_date}.",
		   "Hosting Domain", doc.name)
	return {"domain": doc.name, "status": doc.status}


@frappe.whitelist()
def retry_domain_registration(name: str) -> dict:
	"""Staff action: retry a failed/cancelled registration with the same key."""
	require_staff()
	doc = frappe.get_doc("Hosting Domain", name)
	if doc.status != "Cancelled":
		frappe.throw(f"Only Cancelled registrations can be retried, not {doc.status}", frappe.ValidationError)
	doc.status = "Pending Registration"
	doc.save()
	try:
		result = get_registrar_driver(doc.registrar_account).register(doc.domain_name)
	except ProvisioningError as exc:
		doc.status = "Cancelled"
		doc.failure_reason = f"Registration retry failed ({exc.error_type}): {exc}"[:1000]
		doc.save(ignore_permissions=True)
		return {"domain": doc.name, "status": doc.status, "error": str(exc)}
	doc.registration_date = doc.registration_date or today()
	doc.expiry_date = getdate(result.get("expiry"))
	doc.status = "Active"
	doc.failure_reason = None
	doc.save(ignore_permissions=True)
	notify(doc.customer, f"Domain {doc.domain_name} registered", "The retry succeeded.", "Hosting Domain", doc.name)
	return {"domain": doc.name, "status": doc.status}


def _renewal_invoice(domain, years=1):
	key = f"{domain.name}-renew-{domain.expiry_date}-{years}"
	return billing.issue_invoice(
		billable_customer(domain.customer),
		[{
			"description": f"Domain renewal {domain.domain_name} x {years} year(s)",
			"qty": 1,
			"unit_price": RENEWAL_PRICE * years,
			"line_total": RENEWAL_PRICE * years,
		}],
		currency=RENEWAL_CURRENCY,
		idempotency_key=key,
	)


@frappe.whitelist()
def renew_domain(name: str, years: int = 1) -> dict:
	"""Renew a domain. Invoices first (idempotent); registrar renews once paid."""
	doc = frappe.get_doc("Hosting Domain", name)
	if doc.status not in ("Active", "Grace Period", "Expired"):
		frappe.throw(f"Domain {doc.status} cannot be renewed", frappe.ValidationError)
	invoice = _renewal_invoice(doc, years)
	doc.renewal_invoice = invoice.name
	doc.renewal_idempotency_key = invoice.idempotency_key
	doc.save(ignore_permissions=True)
	if invoice.status != "Paid":
		notify(doc.customer, f"Domain {doc.domain_name} renewal invoiced",
			   f"Invoice {invoice.name} is {invoice.status}; the registrar renews on payment.",
			   "Hosting Domain", doc.name)
		return {"domain": doc.name, "status": doc.status, "invoice": invoice.name, "renewed": False}
	try:
		result = get_registrar_driver(doc.registrar_account).renew(doc.domain_name, years=years)
	except ProvisioningError as exc:
		doc.failure_reason = f"Renewal failed ({exc.error_type}): {exc}"[:1000]
		doc.save(ignore_permissions=True)
		notify(doc.customer, f"Domain {doc.domain_name} renewal failed",
			   f"Payment is recorded but the registrar returned an error: {exc}. Staff will retry.",
			   "Hosting Domain", doc.name)
		return {"domain": doc.name, "status": doc.status, "invoice": invoice.name, "renewed": False, "error": str(exc)}
	doc.expiry_date = getdate(result.get("expiry"))
	doc.status = "Active"
	doc.failure_reason = None
	doc.renewal_invoice = None
	doc.save(ignore_permissions=True)
	notify(doc.customer, f"Domain {doc.domain_name} renewed", f"Your domain is active until {doc.expiry_date}.",
		   "Hosting Domain", doc.name)
	return {"domain": doc.name, "status": doc.status, "renewed": True}


@frappe.whitelist()
def transfer_domain(name: str, auth_code: str) -> dict:
	"""Request an inbound transfer; completes through the registrar."""
	require_staff()
	doc = frappe.get_doc("Hosting Domain", name)
	if doc.status != "Active":
		frappe.throw(f"Only Active domains can be transferred, not {doc.status}", frappe.ValidationError)
	doc.status = "Transfer Pending"
	doc.transfer_status = "Requested"
	doc.save()
	try:
		result = get_registrar_driver(doc.registrar_account).transfer(doc.domain_name, auth_code)
	except ProvisioningError as exc:
		doc.status = "Active"
		doc.transfer_status = "Failed"
		doc.failure_reason = f"Transfer failed ({exc.error_type}): {exc}"[:1000]
		doc.save(ignore_permissions=True)
		return {"domain": doc.name, "status": doc.status, "error": str(exc)}
	doc.status = "Active"
	doc.transfer_status = "Completed"
	doc.expiry_date = getdate(result.get("expiry"))
	doc.failure_reason = None
	doc.save(ignore_permissions=True)
	notify(doc.customer, f"Domain {doc.domain_name} transferred", "The transfer completed.",
		   "Hosting Domain", doc.name)
	return {"domain": doc.name, "status": doc.status}


@frappe.whitelist()
def update_nameservers(name: str, nameservers: list | str) -> dict:
	"""Push nameservers to the registrar and store the confirmed set."""
	require_staff()
	doc = frappe.get_doc("Hosting Domain", name)
	servers = [s.strip() for s in (nameservers if isinstance(nameservers, list) else str(nameservers).splitlines()) if s.strip()]
	try:
		result = get_registrar_driver(doc.registrar_account).set_nameservers(doc.domain_name, servers)
	except ProvisioningError as exc:
		doc.failure_reason = f"Nameserver update failed ({exc.error_type}): {exc}"[:1000]
		doc.save(ignore_permissions=True)
		return {"domain": doc.name, "error": str(exc)}
	doc.nameservers = "\n".join(result.get("nameservers") or servers)
	doc.failure_reason = None
	doc.save(ignore_permissions=True)
	return {"domain": doc.name, "nameservers": doc.nameservers}


def add_dns_record(domain: str, record_type: str, host: str, value: str, ttl: int = 3600, priority: int = 0) -> object:
	"""Add a DNS record; exact duplicates are refused."""
	doc = frappe.get_doc("Hosting Domain", domain)
	if doc.status == "Terminated":
		frappe.throw("DNS cannot be managed on a Terminated domain", frappe.ValidationError)
	dup = frappe.db.get_value(
		"Hosting DNS Record",
		{"domain": doc.name, "record_type": record_type, "host": host or "@", "value": value, "status": "Active"},
		"name",
	)
	if dup:
		frappe.throw("Identical active DNS record already exists", frappe.ValidationError)
	return frappe.get_doc(
		{
			"doctype": "Hosting DNS Record",
			"domain": doc.name,
			"record_type": record_type,
			"host": host or "@",
			"value": value,
			"ttl": ttl or 3600,
			"priority": priority or 0,
			"status": "Active",
		}
	).insert()


def remove_dns_record(name: str) -> dict:
	doc = frappe.get_doc("Hosting DNS Record", name)
	doc.status = "Inactive"
	doc.save()
	return {"record": doc.name, "status": doc.status}


def _send_reminder(doc, stage: int) -> None:
	notify(doc.customer, f"Domain {doc.domain_name} expires in {stage} day(s)",
		   f"Your domain expires on {doc.expiry_date}. Renew to avoid suspension.",
		   "Hosting Domain", doc.name)
	frappe.db.set_value(
		"Hosting Domain", doc.name,
		{"last_reminder_at": now_datetime(), "last_reminder_stage": str(stage)},
	)


def process_domain_renewals(as_of=None) -> dict:
	"""Daily job: reminders, auto-renewal invoices, and expiry progression."""
	day = getdate(as_of) if as_of else getdate(today())
	ran = {"reminded": 0, "renewal_invoices": 0, "renewed": 0, "expired": 0, "progressed": 0}
	for row in frappe.get_all("Hosting Domain", filters={"status": ("in", ["Active", "Transfer Pending"])},
							  fields=["name"]):
		doc = frappe.get_doc("Hosting Domain", row.name)
		if not doc.expiry_date:
			continue
		days_left = date_diff(getdate(doc.expiry_date), day)
		for stage in sorted(REMINDER_STAGES):
			if days_left <= stage and str(doc.last_reminder_stage or "") != str(stage):
				_send_reminder(doc, stage)
				doc.reload()
				ran["reminded"] += 1
				break
		if doc.auto_renew and 0 <= days_left <= AUTO_RENEW_WITHIN_DAYS and doc.status == "Active":
			invoice = _renewal_invoice(doc)
			if not doc.renewal_invoice:
				doc.renewal_invoice = invoice.name
				doc.save(ignore_permissions=True)
				ran["renewal_invoices"] += 1
			if invoice.status == "Paid":
				out = renew_domain(doc.name)
				if out.get("renewed"):
					ran["renewed"] += 1
		if days_left < 0:
			doc.status = "Expired"
			doc.save(ignore_permissions=True)
			ran["expired"] += 1
			notify(doc.customer, f"Domain {doc.domain_name} expired",
				   "Your domain is expired. Renew within the grace period to restore it.",
				   "Hosting Domain", doc.name)
		frappe.db.commit()
	for row in frappe.get_all("Hosting Domain", filters={"status": ("in", ["Expired", "Grace Period", "Redemption"])},
							  fields=["name", "status", "expiry_date"]):
		doc = frappe.get_doc("Hosting Domain", row.name)
		overdue = date_diff(day, getdate(doc.expiry_date)) if doc.expiry_date else 0
		nxt = None
		if doc.status == "Expired" and overdue >= GRACE_DAYS:
			nxt = "Grace Period"
		elif doc.status == "Grace Period" and overdue >= GRACE_DAYS + REDEMPTION_DAYS:
			nxt = "Redemption"
		elif doc.status == "Redemption" and overdue >= GRACE_DAYS + 2 * REDEMPTION_DAYS:
			nxt = "Terminated"
		if nxt:
			doc.status = nxt
			doc.save(ignore_permissions=True)
			ran["progressed"] += 1
			notify(doc.customer, f"Domain {doc.domain_name} is now {nxt}",
				   "Renew now to recover the domain." if nxt != "Terminated" else "The domain was terminated.",
				   "Hosting Domain", doc.name)
		frappe.db.commit()
	return ran
