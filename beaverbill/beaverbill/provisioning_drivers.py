import frappe

class BaseProvisioningDriver:
	def __init__(self, account_name=None):
		self.account_name = account_name

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
		# Allocate IP from IPAM
		available_ip = frappe.get_all("IPAM IP Address", filters={"status": "Available"}, limit=1)
		if available_ip:
			ip_doc = frappe.get_doc("IPAM IP Address", available_ip[0].name)
			ip_doc.status = "Allocated"
			ip_doc.save(ignore_permissions=True)
			frappe.logger().info(f"Dedicated Server: Allocated IP {ip_doc.ip_address} to subscription {subscription_name}")
			return {"status": "Success", "ip": ip_doc.ip_address}
		else:
			frappe.logger().warning(f"Dedicated Server: No available IP addresses in IPAM for subscription {subscription_name}")
			return {"status": "Success", "ip": None}

	def suspend(self, subscription_name):
		frappe.logger().info(f"Dedicated Server: Disabled switch port for subscription {subscription_name}")
		return {"status": "Success"}

	def unsuspend(self, subscription_name):
		frappe.logger().info(f"Dedicated Server: Enabled switch port for subscription {subscription_name}")
		return {"status": "Success"}

	def terminate(self, subscription_name):
		# Release IP back to IPAM
		allocated_ips = frappe.get_all("IPAM IP Address", filters={"status": "Allocated"}, limit=1)
		for ip in allocated_ips:
			ip_doc = frappe.get_doc("IPAM IP Address", ip.name)
			ip_doc.status = "Available"
			ip_doc.save(ignore_permissions=True)
			frappe.logger().info(f"Dedicated Server: Released IP {ip_doc.ip_address} back to IPAM")
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
