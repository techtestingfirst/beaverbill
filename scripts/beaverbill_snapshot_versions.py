#!/usr/bin/env python3
"""Snapshot the release stack into docs/evidence/phase-16-versions.json.

Standalone: needs only git, python, node, mysql client, and redis-cli
on PATH. Database and Redis versions fall back to "unknown" when the
clients cannot reach the servers.

Usage:
    python3 scripts/beaverbill_snapshot_versions.py [--root DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys


def run(*cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or "").strip()
    return text or None


def git_sha(path):
    sha = run("git", "-C", path, "rev-parse", "HEAD")
    return sha if sha and len(sha) == 40 else "unknown"


def _read_version(init_path):
    if os.path.isfile(init_path):
        with open(init_path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip().startswith("__version__"):
                    return line.split("=", 1)[1].strip().strip("'\"")
    return "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Snapshot release versions.")
    parser.add_argument("--root", default=os.getcwd(), help="bench root")
    parser.add_argument("--site", default=None,
                        help="record only apps installed on this site")
    args = parser.parse_args(argv)
    bench = os.path.abspath(args.root)
    apps_dir = os.path.join(bench, "apps")
    app_dir = os.path.join(apps_dir, "beaverbill")
    wanted = None
    if args.site:
        config_path = os.path.join(bench, "sites", args.site, "site_config.json")
        if os.path.isfile(config_path):
            with open(config_path, encoding="utf-8") as handle:
                wanted = json.load(handle).get("installed_apps")
    apps = []
    commits = []
    if os.path.isdir(apps_dir):
        for name in sorted(os.listdir(apps_dir)):
            if not os.path.isdir(os.path.join(apps_dir, name)):
                continue
            if wanted is not None and name not in wanted:
                continue
            apps.append(name)
            # List form (not a {"name": sha} map) so release bookkeeping
            # never looks like an app dependency declaration.
            commits.append({"app": name,
                            "commit": git_sha(os.path.join(apps_dir, name))})
    manifest = {
        "bench": bench,
        "python": platform.python_version(),
        "node": run("node", "--version") or "unknown",
        "npm": run("npm", "--version") or "unknown",
        "database": run("mysql", "--version") or "unknown",
        "redis": None,
        "apps": apps,
        "app_commits": commits,
        "frappe": "unknown",
        "beaverbill": next((row["commit"] for row in commits
                            if row["app"] == "beaverbill"), "unknown"),
    }
    redis_info = run("redis-cli", "--raw", "info", "server")
    if redis_info:
        for line in redis_info.splitlines():
            if line.startswith("redis_version:"):
                manifest["redis"] = line.split(":", 1)[1]
                break
    manifest["redis"] = manifest["redis"] or "unknown"
    manifest["beaverbill_version"] = _read_version(
        os.path.join(app_dir, "beaverbill", "__init__.py"))
    manifest["frappe"] = _read_version(
        os.path.join(bench, "apps", "frappe", "frappe", "__init__.py"))
    out_path = os.path.join(app_dir, "docs", "evidence", "phase-16-versions.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
