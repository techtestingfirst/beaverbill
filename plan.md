# Beaver Bill Implementation Plan

## 1. Project Overview
Beaver Bill is an automated billing and service provisioning application for web hosting providers built on Frappe Framework. It supports multiple upstream hosting modalities:
- Reseller accounts (cPanel/WHM, DirectAdmin, Plesk).
- Cloud and VPS providers (Hetzner Cloud, OVHcloud, DigitalOcean, etc.).
- On-premise hypervisors and private infrastructure (Proxmox VE, OpenNebula).
- Bare metal dedicated servers and colocation infrastructure (IPAM, rack management, switch ports, IPMI).
- Add-on services: domains, SSL certificates, additional IPs, floating storage, backup storage.

### Core Integrations
- **Backend**: Frappe Framework (`beaverbill` app) on site `beaverbill.localhost`.
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
- Infrastructure DocTypes: