#!/usr/bin/env bash
# Phase gate for Beaver Bill. Runs the checks for a phase and marks the
# phase complete only when every required check passes.
#
# Usage: bash scripts/run_phase_gate.sh <phase-id> [evidence-path...]
set -euo pipefail

if [ "$#" -lt 1 ]; then
	echo "Usage: bash scripts/run_phase_gate.sh <phase-id> [evidence-path...]" >&2
	exit 2
fi

PHASE_ID="$1"
shift
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT_FILE="$(mktemp)"

cleanup() {
	rm -f "$REPORT_FILE"
}
trap cleanup EXIT

echo "Running phase gate for ${PHASE_ID}..."

if python3 "$ROOT_DIR/scripts/beaverbill_phase_check.py" "$PHASE_ID" --root "$ROOT_DIR" | tee "$REPORT_FILE"; then
	echo "All required checks passed."
	if [ "$#" -gt 0 ]; then
		EVIDENCE_ARGS=()
		for path in "$@"; do
			EVIDENCE_ARGS+=(--evidence "$path")
		done
		python3 "$ROOT_DIR/scripts/mark_phase_complete.py" "$PHASE_ID" --root "$ROOT_DIR" "${EVIDENCE_ARGS[@]}"
	else
		python3 "$ROOT_DIR/scripts/mark_phase_complete.py" "$PHASE_ID" --root "$ROOT_DIR"
	fi
else
	FAILED=$(python3 -c "import json; print(', '.join(c['name'] for c in json.load(open('$REPORT_FILE'))['checks'] if c['required'] and not c['passed']))")
	echo "PHASE NOT COMPLETE"
	echo "Phase: ${PHASE_ID}"
	echo "Failed checks: ${FAILED}"
	echo "Process file: not marked complete"
	echo "Progress file: not marked complete"
	echo "Next action: fix the failed checks and run the phase gate again."
	exit 1
fi
