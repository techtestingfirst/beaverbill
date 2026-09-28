# Phase 1 — Foundation and Infrastructure Compatibility Hardening

Date: 2026-09-28. All changes are additive: no DocType, field, role, API, or
status value was renamed or removed. Existing tests pass unchanged.

## 1. Schema additions (all optional)

- `IPAM Subnet`: `ip_version` (Select IPv4/IPv6, read-only, set by
  `validate`), `vlan_id` (Int), DB index on `cidr`.
- `IPAM IP Address`: status gains `Released` and `Quarantined` (existing
  `Available`, `Reserved`, `Allocated` untouched); `ip_version` (read-only);
  `allocated_at` (Datetime, read-only); `track_changes = 1`;
  composite index on `(status, subnet)`.
- `Server Node`: `datacenter` (Link to Hosting Datacenter),
  `cpu_cores_total` (Int), `ram_gb_total` (Float), `maintenance_mode`
  (Check), `maintenance_notes` (Small Text); index on `status`.
- `Datacenter Asset`: `datacenter` (Link to Hosting Datacenter).
- New `Hosting Datacenter`: name (unique), region, availability zone,
  status (Active/Maintenance/Decommissioned), notes. Admin full, Support read.
- New `IPAM Allocation Log`: ip link, action
  (Allocated/Released/Reserved/Quarantined), reference doctype/name.
  Read-only for staff; written only by server code. Indexed on `ip_address`.

## 2. Server-side enforcement

- `IPAMSubnet.validate`: CIDR must parse; `ip_version` derived; gateway must
  be a valid IP inside the network; VLAN 1-4094. `after_insert` generation
  unchanged (same 256-address guard, all hosts incl. gateway) plus skip if
  the IP already exists (retry-safe). `on_trash` blocks deletion while any
  IP is not Available, then removes pool IPs.
- `IPAMIPAddress.validate`: address must parse; `ip_version` derived; IP must
  sit inside its subnet CIDR; new docs start Available/Reserved; status moves
  follow the transition map (Available/Reserved/Allocated/Released/
  Quarantined).
- `allocate_ip` / `release_ip` (whitelisted, POST, type-hinted): Hosting Admin
  or System Manager only. Allocation takes a row lock (`for_update`) so two
  concurrent callers cannot take the same IP; exhaustion raises
  `ValidationError`. Every move writes an `IPAM Allocation Log` row.
- `HostingProviderAccount.get_public_fields` (whitelisted): returns only
  non-secret fields to Hosting Admin/Support/System Manager; raises
  `PermissionError` otherwise. Secrets stay in Password fields.
- `DedicatedServerIPAMDriver` now allocates through `allocate_ip` with the
  subscription as reference and releases only that subscription's IPs.
  Exhaustion response shape (`{"status": "Success", "ip": None}`) preserved.

## 3. Reports

- `IP Pool Exhaustion` (ref IPAM Subnet): per-subnet totals, available count,
  used %, OK/Low (<10% free)/Exhausted flag.
- `Duplicate IP Allocation` (ref IPAM Allocation Log): Allocated IPs without
  a reference, and IPs allocated to different references without a release.

## 4. Migration

- `beaverbill.patches.phase1_infra_roles_and_ip_version` (post_model_sync,
  registered in `patches.txt`): creates Hosting Admin/Support/Customer roles
  when missing; recomputes `ip_version` from CIDR/address strings.
  Idempotent; executed on `beaverbill.localhost` via `bench migrate`.
- Uniqueness: no new unique constraints were added (`ip_address`,
  `subnet_name`, `node_name`, `asset_name`, `provider_name`,
  `datacenter_name` were already unique), so no duplicate-risk migration.

## 5. Tests (35 pass on beaverbill.localhost)

- `bench --site beaverbill.localhost run-tests --app beaverbill`: 19
  integration (permission + allocation) and 16 pre-existing, all OK.
- Permission tests: Support read-only on all 7 infra DocTypes; Admin full on
  managed types (log is read-only by design); Customer denied everywhere;
  staff reads admin-owned records (no owner restriction yet — record-level
  ownership arrives with the Phase 3 customer model); customer list access
  denied; provider secrets hidden from non-staff.
- Allocation tests: validate CIDR/gateway/VLAN; IPv6 `/126` generates 3
  versioned IPs; allocate/release lifecycle with audit rows; exhaustion on a
  /30 third call; illegal Allocated-to-Quarantined move rejected; Support
  cannot allocate; driver terminate scoped per subscription; both reports
  execute; patch runs twice cleanly.

## 6. Gaps recorded honestly

- Browser evidence for changed desk forms/lists: not captured (no browser
  binary in this environment). Schema changes are additive and desk forms
  render from DocType metadata; capture pending where a browser exists.
- Evidence: `docs/phase-1-hardening.md`,
  `docs/evidence/phase-1-baseline.json`.
- Commands: `bench --site beaverbill.localhost migrate`,
  `bench --site beaverbill.localhost run-tests --app beaverbill`,
  `python3 scripts/beaverbill_phase_check.py phase-1`.
