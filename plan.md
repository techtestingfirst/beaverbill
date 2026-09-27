# Beaver Bill Implementation Plan

## 1. Project Overview
Beaver Bill is an automated billing and service provisioning application for web hosting providers built on Frappe Framework. It supports multiple upstream hosting modalities:
- Reseller accounts (cPanel/WHM, DirectAdmin, Plesk).
- Cloud and VPS providers (Hetzner Cloud, OVHcloud, DigitalOcean, etc.).
- On-premise hypervisors and private infrastructure (Proxmox VE, OpenNebula).
- Bare metal dedicated servers and colocation infrastructure (IPAM, rack management, switch ports, IPMI).
- Add-on services: domains, SSL certificates, additional IPs, floating storage, backup storage.

### Core Integrations
- **Backend**: Frappe Framework (`beaverbill` app) on site `beaverbill.localhost:8000`.
- **Payments**: `frappe/payments` integration for gateways (Stripe, PayPal, Razorpay) and recurring auto-charge.
- **Support & Ticketing**: `frappe/helpdesk` integration with customer account syncing.
- **Customer Portal**: `frappe-ui` (Vue 3 + Tailwind CSS SPA).
- **Verification & QA**: Automated tests plus browser screenshot captures for every user-facing step, flow, and screen.

---

## 2. Core Functional Requirements

### A. Catalog, Pricing & Discounts
- Product groups: Shared Hosting, Reseller Hosting, VPS, Cloud Instances, Dedicated Servers, Colocation, Domains, Add-ons.
- Billing cycles: Monthly, Quarterly, Semi-Annually, Annually, Biennially, Triennially.
- Configurable options: CPU, RAM, NVMe/SSD Disk, Bandwidth, Extra IPs, OS Templates, Control Panels.
- **Promotions & Discounts Engine**:
  - Promo codes (fixed amount, percentage, recurring vs one-time, lifetime discount).
  - Product-specific and customer-group restrictions.
  - Expiration dates and usage limits per promo code and per customer.

### B. Upgrades & Downgrades
- Upgrade/downgrade between compatible products or configurable option adjustments.
- Automated proration calculation for both billing upgrades (invoice difference) and downgrades (issue credit note/wallet balance).
- Provisioning hook triggered upon paid upgrade/downgrade to resize container, VPS, or adjust cPanel package.

### C. Billing, Invoicing & Subscriptions
- Shopping cart, checkout, invoice generation.
- Integration with `frappe/payments` gateways.
- Automatic subscription renewal, automated capture via stored payment methods.
- Dunning lifecycle: invoice reminder emails, overdue notice, service suspension after grace period, service termination/data purge after termination threshold.
- Customer wallet and credit system.

### D. Upstream & On-Premise Provisioning Adapters
- Modular adapter pattern (`BaseProvisioningDriver`).
- Shared/Reseller: cPanel/WHM API, DirectAdmin API.
- Cloud Providers: Hetzner Cloud API, OVHcloud API.
- Virtualization: Proxmox VE API (QEMU/LXC creation, snapshots, power actions).
- Dedicated & Colocation: DCIM asset allocation (Rack, PDU, Switch Port), IPAM subnet assignment, IPMI power controls, rescue mode trigger.
- Add-on services: Registrar APIs (Namecheap/Enom/ResellerClub), Let's Encrypt / Custom SSL management.

### E. Customer Portal (`frappe-ui`)
- Overview dashboard: active services, unpaid invoices, recent tickets.
- Service management screen:
  - Power control (start, reboot, shutdown).
  - Web console / noVNC integration.
  - Resource usage graphs (bandwidth, CPU, RAM, disk).
  - Root/admin password reset, OS reinstall.
  - Upgrade/Downgrade self-service workflow.
- Invoices & Payment center (pay invoice, download PDF, manage payment methods).
- Helpdesk ticket bridge to `frappe/helpdesk`.

### F. Quality Assurance & Browser Visual Verification
- Backend unit and integration tests for every feature.
- Automated browser screenshot captures using agent browser tooling for all user journeys:
  - Catalog browsing and configuration.
  - Cart, coupon code application, checkout.
  - Invoice payment and receipt.
  - Customer portal dashboard and service management.
  - Upgrade/downgrade workflow.
  - Support ticket interface.
- Git commit per verified step after tests pass.

---

## 3. Phased Implementation Roadmap

### Phase 1: Base Configuration, Roles & Infrastructure Setup
- Verify app configuration, hooks, modules, dependencies.
- Define roles: `Hosting Customer`, `Hosting Support`, `Hosting Admin`.
- Infrastructure DocTypes: `Hosting Provider Account`, `Server Node`, `IPAM Subnet`, `IPAM IP Address`, `Datacenter Asset`.
- Test infrastructure creation and validation.
- Capture desk configuration screenshots.

### Phase 2: Product Catalog, Addons & Discount Engine
- DocTypes: `Hosting Product Group`, `Hosting Product`, `Hosting Configurable Option`, `Hosting Product Addon`.
- Discount DocType: `Hosting Promo Code` and validation service (percentage, fixed amount, recurring, limits).
- Pricing calculation service with multi-currency and billing cycle support.
- Unit tests for discount logic, cycle calculations, and limit enforcement.

### Phase 3: Order Management, Payments & Subscriptions
- DocTypes: `Hosting Order`, `Hosting Order Item`, `Hosting Invoice`, `Hosting Subscription`, `Customer Credit Transaction`.
- Integration with `frappe/payments`.
- Subscription lifecycle scheduler (daily check, dunning, auto-charge, suspension, cancellation).
- Automated tests for checkout, payment webhook handling, and renewal triggers.
- Visual verification of order and invoice records.

### Phase 4: Upgrade and Downgrade Engine
- DocType: `Hosting Service Modification Request`.
- Proration engine: calculate unused period credit vs new product cost.
- Automated generation of invoice (upgrade) or credit note (downgrade).
- Provisioning hook integration to apply changes dynamically on the hypervisor/panel.
- Tests for proration mathematics and state transitions.

### Phase 5: Provisioning Drivers & Upstream Adapters
- Driver architecture: `BaseProvisioningDriver` interface.
- Implement WHM/cPanel driver (create account, suspend, unsuspend, terminate, change package).
- Implement DirectAdmin driver.
- Implement Hetzner Cloud driver (create server, reboot, resize, delete).
- Implement OVHcloud driver.
- Implement Proxmox VE driver (create VM/LXC, power controls, VNC ticket).
- Implement Dedicated Server & IPAM allocation driver (MAC, IP assignment, rescue mode).
- Provisioning background queue and error recovery.

### Phase 6: Customer Portal (`frappe-ui`) & Helpdesk Bridge
- Setup `frappe-ui` SPA frontend in `beaverbill`.
- Customer auth, dashboard, and service details.
- Self-service actions: power controls, VNC console, root password reset, upgrade/downgrade wizard.
- Coupon input and checkout flow in the portal.
- Frappe Helpdesk customer ticketing portal embed/bridge.
- Browser screenshot verification across all desktop and mobile views.

### Phase 7: End-to-End Testing & Security Hardening
- Complete integration tests:
  - Customer registers → browses catalog → applies discount → checks out → payment confirmed → service auto-provisioned.
  - Customer requests upgrade → pays prorated invoice → service resized.
  - Renewal failure simulation → grace period → service suspended → service terminated.
- Security audit against OWASP, safe execution, parameter sanitization, and access checks.
- Documentation and final deployment verification.
