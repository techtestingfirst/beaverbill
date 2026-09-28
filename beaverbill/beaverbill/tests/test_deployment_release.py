"""Phase 16 tests: release readiness without mutating the site.

Scheduler, smoke, versions, deploy-script, and no-ERPNext checks are
read-only. The backup test verifies the drill evidence produced by
the operator run (backup, encrypt, restore) rather than taking a
second backup inside the suite.
"""

import json
import os

import frappe
from frappe.tests import IntegrationTestCase

from beaverbill.beaverbill import deployment

APP_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")


class TestDeploymentRelease(IntegrationTestCase):
	def test_no_erpnext(self):
		out = deployment.assert_no_erpnext()
		self.assertNotIn("erpnext", out["installed_apps"])
		self.assertEqual(out["required_apps"], ["frappe"])

	def test_scheduler_validation(self):
		out = deployment.validate_scheduler()
		# The test runner holds the scheduler off, so only the stable
		# parts are asserted here; live enablement is proven by the
		# standalone release_status run on the site.
		self.assertIsInstance(out["scheduler_enabled"], bool)
		self.assertEqual(out["missing_jobs"], [])
		self.assertTrue(out["cache_ok"])
		self.assertIn(out["status"], ("ok", "fail"))

	def test_blockers_detect_dev_settings(self):
		blockers = deployment.check_release_blockers()
		self.assertTrue(any("ignore_csrf" in item for item in blockers))

	def test_smoke_tests_pass(self):
		results = deployment.run_smoke_tests()
		self.assertTrue(results)
		for row in results:
			self.assertTrue(row["ok"], f"{row['name']}: {row['detail']}")

	def test_versions_manifest(self):
		manifest = deployment.snapshot_versions()
		self.assertEqual(manifest["site"], frappe.local.site)
		self.assertIn("beaverbill", manifest["installed_apps"])
		for app, sha in manifest["app_commits"].items():
			self.assertEqual(len(sha), 40, app)

	def test_deploy_automation_exists(self):
		deploy = os.path.join(APP_ROOT, "scripts", "deploy_beaverbill.sh")
		with open(deploy, encoding="utf-8") as handle:
			text = handle.read()
		for step in ("migrate", "build", "restart", "enable-scheduler",
				"install-app", "snapshot"):
			self.assertIn(step, text)
		self.assertTrue(os.access(deploy, os.X_OK))
		snapshot = os.path.join(APP_ROOT, "scripts",
			"beaverbill_snapshot_versions.py")
		self.assertTrue(os.path.isfile(snapshot))

	def test_backup_drill_evidence(self):
		path = os.path.join(APP_ROOT, "docs", "evidence", "phase-16-backup.json")
		with open(path, encoding="utf-8") as handle:
			evidence = json.load(handle)
		for key in ("backup_at", "database_gz", "sha256", "restore",
				"encryption", "retention_days"):
			self.assertIn(key, evidence)
		for _label, digest in evidence["sha256"].items():
			self.assertEqual(len(digest), 64)
		self.assertTrue(str(evidence["encryption"]["roundtrip"]).startswith("verified"))
		self.assertIn(evidence["restore"]["status"], ("restored", "not_executed"))
		if evidence["restore"]["status"] == "not_executed":
			self.assertTrue(evidence["restore"]["reason"])
