#!/usr/bin/env bash
# Automated Beaver Bill deployment (staging and production).
# Idempotent where the bench CLI allows it: install steps are skipped
# when already done; migrate/build/restart always run.
#
# Usage: bash scripts/deploy_beaverbill.sh <site> [--branch <git-ref>]
set -euo pipefail

if [ "$#" -lt 1 ]; then
	echo "Usage: bash scripts/deploy_beaverbill.sh <site> [--branch <git-ref>]" >&2
	exit 2
fi

SITE="$1"
BRANCH=""
if [ "${2:-}" = "--branch" ]; then
	BRANCH="${3:-}"
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_DIR="$ROOT_DIR/apps/beaverbill"

echo "Deploying BeaverBill to ${SITE}..."

if [ -n "$BRANCH" ]; then
	echo "Checking out ${BRANCH}..."
	git -C "$APP_DIR" fetch origin
	git -C "$APP_DIR" checkout "$BRANCH"
fi

if ! bench --site "$SITE" list-apps 2>/dev/null | grep -q "^beaverbill "; then
	if [ -d "$APP_DIR" ]; then
		echo "Installing existing beaverbill app..."
		bench --site "$SITE" install-app beaverbill
	else
		echo "Fetching beaverbill app..."
		bench get-app beaverbill "$APP_DIR"
		bench --site "$SITE" install-app beaverbill
	fi
else
	echo "beaverbill already installed; skipping install."
fi

echo "Running migrations..."
bench --site "$SITE" migrate

echo "Building frontend..."
bench build --app beaverbill

echo "Restarting services..."
bench restart || supervisorctl restart all || true

echo "Enabling scheduler..."
bench --site "$SITE" enable-scheduler

echo "Running doctor..."
bench doctor || true

echo "Recording versions..."
python3 "$APP_DIR/scripts/beaverbill_snapshot_versions.py" --root "$ROOT_DIR" --site "$SITE"

echo "Deployment to ${SITE} finished. Run post-release smoke tests next:"
echo "  bench --site $SITE execute beaverbill.beaverbill.deployment.release_status"
