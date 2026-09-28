# Beaver Bill Agent Operating Guidelines

This repository implements Beaver Bill, an automated billing, subscription, customer-portal, and service-provisioning system for web-hosting providers built directly on Frappe Framework.

## 1. Absolute Directives

1. **No ERPNext**: Never add ERPNext, ERPNext imports (`import erpnext`), ERPNext DocTypes (`Customer`, `Sales Invoice`, `Payment Entry`, etc.), or ERPNext dependencies. Beaver Bill is self-contained.
2. **Compatibility Preservation**: Do not break or rewrite existing features, DocTypes, APIs, field names, or business logic. All improvements must be additive or wrapped with backward compatibility.
3. **No Manual Status Edits**: Never manually set a phase to `completed` in `process.md` or `progress/phase-status.json`. All status progressions must happen automatically via `scripts/run_phase_gate.sh`.
4. **Current Phase Scope**: Always read `progress/phase-status.json` to determine the current active phase. Implement only the tasks assigned to the active phase.

## 2. Automatic Progress Lifecycle

When working on a phase:
1. Read `plan.md`, `process.md`, `progress/phase-status.json`, and `AGENTS.md`.
2. Ensure you understand all tasks and invariants for the current phase.
3. Perform changes with high code quality, security, and tests.
4. Run the phase gate:
   ```bash
   bash scripts/run_phase_gate.sh <phase-id>
   ```
5. If the phase gate fails, address the reported errors and re-run.

## 3. Tooling and Script Reference

- `scripts/beaverbill_phase_check.py`: Runs automated checks for a phase (ERPNext scanner, unit tests, schema, documentation, evidence).
- `scripts/mark_phase_complete.py`: Atomically updates `progress/phase-status.json` and updates the generated sections in `process.md`.
- `scripts/run_phase_gate.sh`: Runs the full gate pipeline and invokes `mark_phase_complete.py` only when all checks pass.
- `.githooks/pre-commit`: Validates that markers in `process.md` have not been manually tampered with.
