"""Everything hooks.py promises actually exists.

A typo in a dotted path in hooks.py is invisible until the scheduler fires at
2am, so each one is imported here instead.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

APP = "nexus_zkt_integration"
MODULE = "Nexus Biometric Attendance"
DOCTYPES = ("Nexus ZKT Settings", "Nexus ZKT Device", "Nexus Attendance Log")


def resolve(dotted_path):
	return frappe.get_attr(dotted_path)


class TestHooks(FrappeTestCase):
	def setUp(self):
		self.hooks = frappe.get_hooks(app_name=APP)

	def test_the_app_is_installed_on_this_site(self):
		self.assertIn(APP, frappe.get_installed_apps())

	def test_it_declares_hrms_as_required(self):
		self.assertIn("frappe/hrms", self.hooks.get("required_apps", []))

	def test_hrms_really_is_installed(self):
		self.assertIn("hrms", frappe.get_installed_apps())

	def test_the_install_hook_points_at_a_real_function(self):
		self.assertTrue(callable(resolve(self.hooks["after_install"][0])))

	def test_the_uninstall_hook_points_at_a_real_function(self):
		self.assertTrue(callable(resolve(self.hooks["before_uninstall"][0])))

	def test_every_scheduled_job_points_at_a_real_function(self):
		events = self.hooks["scheduler_events"]
		self.assertTrue(events, "the app should schedule something")
		for _when, paths in events.items():
			for path in paths:
				self.assertTrue(callable(resolve(path)), f"{path} is not callable")

	def test_the_hourly_job_is_the_sync(self):
		events = self.hooks["scheduler_events"]
		self.assertIn(f"{APP}.nexus_biometric_attendance.api.scheduled_collection", events["hourly_long"])

	def test_the_weekly_job_clears_the_activity_log(self):
		events = self.hooks["scheduler_events"]
		self.assertIn(f"{APP}.nexus_biometric_attendance.api.purge_journal", events["weekly"])

	def test_the_apps_screen_entry_points_at_a_real_permission_check(self):
		entry = self.hooks["add_to_apps_screen"][0]
		self.assertTrue(callable(resolve(entry["has_permission"])))
		self.assertEqual(entry["name"], APP)

	def test_the_apps_screen_logo_file_ships_with_the_app(self):
		import os

		entry = self.hooks["add_to_apps_screen"][0]
		relative = entry["logo"].replace(f"/assets/{APP}/", "")
		path = frappe.get_app_path(APP, "public", relative)
		self.assertTrue(os.path.exists(path), f"missing logo file: {path}")

	def test_the_app_is_published_under_the_owner_name(self):
		self.assertEqual(self.hooks["app_publisher"][0], "Abbas Raza")
		self.assertEqual(self.hooks["app_license"][0], "mit")


class TestWhitelistedMethods(FrappeTestCase):
	PATHS = (
		f"{APP}.nexus_biometric_attendance.api.collect_now",
		f"{APP}.nexus_biometric_attendance.api.sync_status",
		f"{APP}.nexus_biometric_attendance.api.purge_journal",
		f"{APP}.nexus_biometric_attendance.api.erase_device",
	)

	def test_the_form_and_list_buttons_can_reach_their_methods(self):
		for path in self.PATHS:
			self.assertIn(
				resolve(path),
				frappe.whitelisted,
				f"{path} is called from the browser but is not whitelisted",
			)


class TestTheBrowserAndTheServerAgree(FrappeTestCase):
	"""Method paths written in JS are strings; a rename that misses one fails
	only when somebody clicks the button. Read them out of the files instead."""

	def js_files(self):
		import os

		root = frappe.get_app_path(APP)
		for folder, _dirs, files in os.walk(root):
			for name in files:
				if name.endswith(".js"):
					yield os.path.join(folder, name)

	def test_every_method_the_client_calls_exists_and_is_whitelisted(self):
		import re

		pattern = re.compile(r"nexus_zkt_integration\.[a-z_.]+")
		found = set()
		for path in self.js_files():
			for hit in pattern.findall(open(path).read()):
				if hit.count(".") >= 3:
					found.add(hit)
		self.assertTrue(found, "no server method paths were found in the client scripts")
		for path in sorted(found):
			self.assertIn(
				resolve(path), frappe.whitelisted, f"{path} is called from the browser but is not whitelisted"
			)

	def test_no_reference_to_the_old_module_survives(self):
		import os

		# Assembled rather than written out, so this test does not find itself.
		retired = "nexus_biometric_attendance" + "." + "script"
		root = frappe.get_app_path(APP)
		for folder, _dirs, files in os.walk(root):
			if "__pycache__" in folder or "tests_site" in folder:
				continue
			for name in files:
				if not name.endswith((".py", ".js")):
					continue
				body = open(os.path.join(folder, name)).read()
				self.assertNotIn(
					retired,
					body,
					f"{name} still points at the module that was replaced",
				)


class TestDocTypes(FrappeTestCase):
	def test_all_three_doctypes_are_installed(self):
		for doctype in DOCTYPES:
			self.assertTrue(frappe.db.exists("DocType", doctype), f"missing DocType: {doctype}")

	def test_they_belong_to_this_app_module(self):
		for doctype in DOCTYPES:
			self.assertEqual(frappe.db.get_value("DocType", doctype, "module"), MODULE)

	def test_the_settings_are_a_single(self):
		self.assertTrue(frappe.get_meta("Nexus ZKT Settings").issingle)

	def test_a_device_is_a_child_row_of_the_settings(self):
		self.assertTrue(frappe.get_meta("Nexus ZKT Device").istable)
		field = frappe.get_meta("Nexus ZKT Settings").get_field("devices")
		self.assertEqual(field.fieldtype, "Table")
		self.assertEqual(field.options, "Nexus ZKT Device")

	def test_the_device_password_is_stored_as_a_secret(self):
		field = frappe.get_meta("Nexus ZKT Device").get_field("device_password")
		self.assertEqual(field.fieldtype, "Password")

	def test_the_names_do_not_collide_with_the_upstream_app(self):
		# Every doctype carries the Nexus prefix so this app can be installed on a
		# site that already runs another ZK integration.
		for doctype in DOCTYPES:
			self.assertTrue(doctype.startswith("Nexus "), doctype)

	def test_the_dead_clear_on_fetch_checkbox_is_gone(self):
		# Upstream ships this field with the clearing code commented out. Clearing
		# is a deliberate button here instead, so the field must not come back.
		self.assertIsNone(frappe.get_meta("Nexus ZKT Device").get_field("clear_from_device_on_fetch"))


class TestWorkspace(FrappeTestCase):
	def test_the_workspace_is_installed(self):
		self.assertTrue(frappe.db.exists("Workspace", "Nexus ZKT"))

	def test_the_apps_screen_route_opens_that_workspace(self):
		route = frappe.get_hooks(app_name=APP)["add_to_apps_screen"][0]["route"]
		self.assertEqual(route, "/app/nexus-zkt")

	def test_every_workspace_link_points_at_something_real(self):
		workspace = frappe.get_doc("Workspace", "Nexus ZKT")
		for row in workspace.links:
			if row.type != "Link" or row.link_type != "DocType":
				continue
			self.assertTrue(frappe.db.exists("DocType", row.link_to), f"broken workspace link: {row.link_to}")

	def test_every_shortcut_points_at_something_real(self):
		workspace = frappe.get_doc("Workspace", "Nexus ZKT")
		self.assertTrue(workspace.shortcuts, "the workspace should have shortcuts")
		for row in workspace.shortcuts:
			if row.type != "DocType":
				continue
			self.assertTrue(frappe.db.exists("DocType", row.link_to), f"broken shortcut: {row.link_to}")
