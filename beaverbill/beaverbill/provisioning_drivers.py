import hashlib
import time
import uuid

import frappe

DRIVER_CONTRACT_VERSION = "2.0"
LEGACY_CONTRACT_VERSION = "1.0"

ERROR_TYPES = ("transient", "rate_limited", "capacity", "permanent", "unknown")

# Actions the orchestration engine may route through a driver. Legacy
# method names are preserved; this tuple only names them for logging.
DRIVER_ACTIONS = (
	"provision",
	"suspend",
	"unsuspend",
	"terminate",
	"resize",
	"reboot",
	"get_vnc_console",
	"describe",
)


class ProvisioningError(Exception):
	"""Classified driver failure used for retry decisions.

	`error_type` is one of ERROR_TYPES. `retryable` defaults from the
	type but a driver may override it explicitly.
	"""

	_DEFAULT_RETRYABLE = {
		"transient": True,
		"rate_limited": True,
		"capacity": True,
		"permanent": False,
		"unknown": False,
	}

	def __init__(self, message, error_type="unknown", retryable=None, provider_code=None):
		super().__init__(message)
		if error_type not in ERROR_TYPES:
			error_type = "unknown"
		self.error_type = error_type
		self.retryable = self._DEFAULT_RETRYABLE[error_type] if retryable is None else bool(retryable)
		self.provider_code = provider_code


def new_correlation_id():
	return uuid.uuid4().hex


def safe_summary(payload, limit=1000):
	"""Render a log-safe summary of a driver payload (no secrets)."""
	if payload is None:
		return ""
	text = str(payload)
	for key in ("api_key", "api_secret", "password", "token", "secret"):
		if key in text.lower():
			return "<redacted>"
	return text[:limit]


def classify_exception(exc):
	"""Map an arbitrary driver exception to a (error_type, retryable) pair."""
	if isinstance(exc, ProvisioningError):
		return exc.error_type, exc.retryable
	message = str(exc).lower()
	if any(word in message for word in ("rate limit", "rate-limit", "ratelimit", "too many requests", "429")):
		return "rate_limited", True
	if any(word in message for word in ("capacity", "exhausted", "no available", "out of stock", "quota")):
		return "capacity", True
	if any(word in message for word in ("timeout", "timed out", "connection", "temporary", "try again", "503", "502")):
		return "transient", True
	if any(word in message for word in ("not found", "invalid", "unknown driver", "unsupported", "refused")):
		return "permanent", False
	return "unknown", False


class BaseProvisioningDriver:
	"""Versioned driver contract (v2.0). Legacy signatures preserved.

	Existing drivers override the verb methods exactly as before. The
	engine routes calls through `call_driver_action` so old dict
	returns and plain exceptions keep working via normalization.
	"""

	contract_version = DRIVER_CONTRACT_VERSION

	def __init__(self, account_name=None):
		self.account_name = account_name

	def capabilities(self):
		"""Advertise supported actions. Drivers override additively."""
		return {
			"contract_version": getattr(self, "contract_version", LEGACY_CONTRACT_VERSION),
			"provision": True,
			"suspend": True,
			"unsuspend": True,
			"terminate": True,
			"resize": True,
			"reboot": hasattr(self, "reboot") and callable(getattr(self, "reboot", None)),
			"get_vnc_console": hasattr(self, "get_vnc_console")
			and callable(getattr(self, "get_vnc_console", None)),
			"describe": type(self).describe is not BaseProvisioningDriver.describe,
		}

	def describe(self, subscription_name):
		"""Return remote resource state for reconciliation.

	 Default raises NotImplementedError; the engine records an
	 `Unknown` verdict instead of failing. Drivers implement this
	 additively when their upstream API supports a status query.
	 """
		raise NotImplementedError(
			f"{type(self).__name__} does not implement describe(); reconciliation stays Unknown"
		)

	def provision(self, subscription_name, details=None):
		raise NotImplementedError()

	def suspend(self, subscription_name):
		raise NotImplementedError()

	def unsuspend(self, subscription_name):
		raise NotImplementedError()

	def terminate(self, subscription_name):
		raise NotImplementedError()

	def resize(self, subscription_name, new_product_name):
		raise NotImplementedError()

	def reboot(self, subscription_name):
		raise NotImplementedError()

	def get_vnc_console(self, subscription_name):
		raise NotImplementedError()


class CPanelWHMDriver(BaseProvisioningDriver):
	def provision(self, subscription_name, details=None):
		frappe.logger().info(f"cPanel/WHM: Provisioned account for subscription {subscription_name}")
		return {"status": "Success", "username": "user_" + subscription_name[:8]}

	def suspend(self, subscription_name):
		frappe.logger().info(f"cPanel/WHM: Suspended account for subscription {subscription_name}")
		return {"status": "Success"}

	def unsuspend(self, subscription_name):
		frappe.logger().info(f"cPanel/WHM: Unsuspended account for subscription {subscription_name}")
		return {"status": "Success"}

	def terminate(self, subscription_name):
		frappe.logger().info(f"cPanel/WHM: Terminated account for subscription {subscription_name}")
		return {"status": "Success"}

	def resize(self, subscription_name, new_product_name):
		frappe.logger().info(f"cPanel/WHM: Resized account package for subscription {subscription_name} to {new_product_name}")
		return {"status": "Success"}


class DirectAdminDriver(BaseProvisioningDriver):
	def provision(self, subscription_name, details=None):
		frappe.logger().info(f"DirectAdmin: Provisioned account for subscription {subscription_name}")
		return {"status": "Success"}

	def suspend(self, subscription_name):
		frappe.logger().info(f"DirectAdmin: Suspended account for subscription {subscription_name}")
		return {"status": "Success"}

	def unsuspend(self, subscription_name):
		frappe.logger().info(f"DirectAdmin: Unsuspended account for subscription {subscription_name}")
		return {"status": "Success"}

	def terminate(self, subscription_name):
		frappe.logger().info(f"DirectAdmin: Terminated account for subscription {subscription_name}")
		return {"status": "Success"}

	def resize(self, subscription_name, new_product_name):
		frappe.logger().info(f"DirectAdmin: Resized account package for subscription {subscription_name} to {new_product_name}")
		return {"status": "Success"}


class HetznerCloudDriver(BaseProvisioningDriver):
	def provision(self, subscription_name, details=None):
		frappe.logger().info(f"Hetzner Cloud: Created server for subscription {subscription_name}")
		return {"status": "Success", "ip": "192.168.1.100"}

	def suspend(self, subscription_name):
		frappe.logger().info(f"Hetzner Cloud: Powered off server for subscription {subscription_name}")
		return {"status": "Success"}

	def unsuspend(self, subscription_name):
		frappe.logger().info(f"Hetzner Cloud: Powered on server for subscription {subscription_name}")
		return {"status": "Success"}

	def terminate(self, subscription_name):
		frappe.logger().info(f"Hetzner Cloud: Deleted server for subscription {subscription_name}")
		return {"status": "Success"}

	def resize(self, subscription_name, new_product_name):
		frappe.logger().info(f"Hetzner Cloud: Resized server for subscription {subscription_name} to {new_product_name}")
		return {"status": "Success"}

	def reboot(self, subscription_name):
		frappe.logger().info(f"Hetzner Cloud: Rebooted server for subscription {subscription_name}")
		return {"status": "Success"}


class OVHCloudDriver(BaseProvisioningDriver):
	def provision(self, subscription_name, details=None):
		frappe.logger().info(f"OVHcloud: Created instance for subscription {subscription_name}")
		return {"status": "Success"}

	def suspend(self, subscription_name):
		frappe.logger().info(f"OVHcloud: Suspended instance for subscription {subscription_name}")
		return {"status": "Success"}

	def unsuspend(self, subscription_name):
		frappe.logger().info(f"OVHcloud: Unsuspended instance for subscription {subscription_name}")
		return {"status": "Success"}

	def terminate(self, subscription_name):
		frappe.logger().info(f"OVHcloud: Terminated instance for subscription {subscription_name}")
		return {"status": "Success"}

	def resize(self, subscription_name, new_product_name):
		frappe.logger().info(f"OVHcloud: Resized instance for subscription {subscription_name} to {new_product_name}")
		return {"status": "Success"}


class ProxmoxVEDriver(BaseProvisioningDriver):
	def provision(self, subscription_name, details=None):
		frappe.logger().info(f"Proxmox VE: Created VM/LXC container for subscription {subscription_name}")
		return {"status": "Success", "vmid": 1001}

	def suspend(self, subscription_name):
		frappe.logger().info(f"Proxmox VE: Stopped VM/LXC container for subscription {subscription_name}")
		return {"status": "Success"}

	def unsuspend(self, subscription_name):
		frappe.logger().info(f"Proxmox VE: Started VM/LXC container for subscription {subscription_name}")
		return {"status": "Success"}

	def terminate(self, subscription_name):
		frappe.logger().info(f"Proxmox VE: Destroyed VM/LXC container for subscription {subscription_name}")
		return {"status": "Success"}

	def resize(self, subscription_name, new_product_name):
		frappe.logger().info(f"Proxmox VE: Resized VM/LXC resources for subscription {subscription_name} to {new_product_name}")
		return {"status": "Success"}

	def reboot(self, subscription_name):
		frappe.logger().info(f"Proxmox VE: Rebooted VM/LXC container for subscription {subscription_name}")
		return {"status": "Success"}

	def get_vnc_console(self, subscription_name):
		frappe.logger().info(f"Proxmox VE: Generated VNC ticket for subscription {subscription_name}")
		return {"status": "Success", "url": "https://proxmox.local/?console=vnc&vmid=1001"}


class DedicatedServerIPAMDriver(BaseProvisioningDriver):
	def provision(self, subscription_name, details=None):
		# Allocate IP from IPAM, scoped to this subscription.
		from beaverbill.beaverbill.doctype.ipam_ip_address.ipam_ip_address import allocate_ip

		try:
			ip_name = allocate_ip(
				reference_doctype="Hosting Subscription",
				reference_name=subscription_name,
			)
		except frappe.ValidationError:
			frappe.logger().warning(f"Dedicated Server: No available IP addresses in IPAM for subscription {subscription_name}")
			return {"status": "Success", "ip": None}
		ip_address = frappe.db.get_value("IPAM IP Address", ip_name, "ip_address")
		frappe.logger().info(f"Dedicated Server: Allocated IP {ip_address} to subscription {subscription_name}")
		return {"status": "Success", "ip": ip_address}

	def suspend(self, subscription_name):
		frappe.logger().info(f"Dedicated Server: Disabled switch port for subscription {subscription_name}")
		return {"status": "Success"}

	def unsuspend(self, subscription_name):
		frappe.logger().info(f"Dedicated Server: Enabled switch port for subscription {subscription_name}")
		return {"status": "Success"}

	def terminate(self, subscription_name):
		# Release only IPs allocated to this subscription.
		from beaverbill.beaverbill.doctype.ipam_ip_address.ipam_ip_address import release_ip

		owned = frappe.get_all(
			"IPAM IP Address",
			filters={
				"status": "Allocated",
				"allocated_to_doctype": "Hosting Subscription",
				"allocated_to_name": subscription_name,
			},
			pluck="name",
		)
		for ip_name in owned:
			release_ip(ip_name)
			frappe.logger().info(f"Dedicated Server: Released IP {ip_name} back to IPAM")
		frappe.logger().info(f"Dedicated Server: Re-imaged server and cleared switch port for subscription {subscription_name}")
		return {"status": "Success"}

	def resize(self, subscription_name, new_product_name):
		frappe.logger().info(f"Dedicated Server: Resized switch port bandwidth limit for subscription {subscription_name} to {new_product_name}")
		return {"status": "Success"}


def get_provisioning_driver(driver_type, account_name=None):
	drivers = {
		"cPanel/WHM": CPanelWHMDriver,
		"DirectAdmin": DirectAdminDriver,
		"Hetzner Cloud": HetznerCloudDriver,
		"OVHcloud": OVHCloudDriver,
		"Proxmox VE": ProxmoxVEDriver,
		"Dedicated Server": DedicatedServerIPAMDriver
	}
	driver_class = drivers.get(driver_type)
	if not driver_class:
		raise ValueError(f"Unknown provisioning driver type: {driver_type}")
	return driver_class(account_name)


def normalize_result(result):
	"""Normalize a legacy driver return into a metadata-safe dict."""
	if result is None:
		return {"status": "Success"}
	if isinstance(result, dict):
		return dict(result)
	return {"status": "Success", "detail": safe_summary(result, 500)}


def call_driver_action(driver, action, *args, **kwargs):
	"""Invoke a driver verb with timing, normalization, and classification.

	Returns (result_dict, elapsed_ms). Raises ProvisioningError with a
	classified error_type so the engine can decide retries. Legacy
	plain exceptions are wrapped, never propagated raw.
	"""
	if action not in DRIVER_ACTIONS:
		raise ProvisioningError(f"Unsupported driver action: {action}", error_type="permanent")
	method = getattr(driver, action, None)
	if not callable(method):
		raise ProvisioningError(
			f"Driver {type(driver).__name__} does not support {action}",
			error_type="permanent",
		)
	started = time.monotonic()
	try:
		result = normalize_result(method(*args, **kwargs))
	except ProvisioningError:
		raise
	except NotImplementedError as exc:
		raise ProvisioningError(str(exc), error_type="unknown", retryable=False) from exc
	except Exception as exc:
		error_type, retryable = classify_exception(exc)
		raise ProvisioningError(str(exc), error_type=error_type, retryable=retryable) from exc
	elapsed_ms = int((time.monotonic() - started) * 1000)
	return result, elapsed_ms


def request_hash(action, args, kwargs):
	"""Stable non-secret hash of a driver call for request logging."""
	digest = hashlib.sha256()
	digest.update(action.encode())
	digest.update(safe_summary((args, sorted(str(kwargs.items()))), 2000).encode())
	return digest.hexdigest()
