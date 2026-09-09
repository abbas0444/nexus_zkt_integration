"""The settings form: what it accepts and what it refuses."""

import frappe
from frappe.tests.utils import FrappeTestCase

SETTINGS = "Nexus ZKT Settings"


class TestSettings(FrappeTestCase):
	def settings(self):
		doc = frappe.get_doc(SETTINGS)
		doc.set("devices", [])
		return doc

	def add(self, doc, device_id, ip=None):
		# Each row gets its own address unless the test is about sharing one,
		# so the name checks below fail for the reason they are testing.
		nth = len(doc.get("devices") or [])
		doc.append(
			"devices",
			{"device_id": device_id, "ip": ip or f"192.0.2.{10 + nth}", "punch_direction": "AUTO"},
		)

	def test_the_single_exists_after_install(self):
		self.assertTrue(frappe.get_doc(SETTINGS))

	def test_two_devices_with_different_names_are_fine(self):
		doc = self.settings()
		self.add(doc, "front-door")
		self.add(doc, "back-gate")
		doc.save()
		self.assertEqual(len(doc.devices), 2)

	def test_two_devices_with_the_same_name_are_refused(self):
		# Both rows would write to the same Last Read, so one device would silently
		# stop being read.
		doc = self.settings()
		self.add(doc, "front-door")
		self.add(doc, "front-door", ip="192.0.2.11")
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_the_duplicate_message_names_the_device(self):
		doc = self.settings()
		self.add(doc, "front-door")
		self.add(doc, "front-door")
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.save()
		self.assertIn("front-door", str(caught.exception))

	def test_surrounding_spaces_do_not_smuggle_a_duplicate_through(self):
		doc = self.settings()
		self.add(doc, "front-door")
		self.add(doc, "  front-door  ")
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_one_machine_listed_twice_is_refused(self):
		# Both rows would be read, and the punches would file under whichever
		# name came first - which looks like the other door has stopped working.
		doc = self.settings()
		self.add(doc, "door-a", ip="192.0.2.50")
		self.add(doc, "door-b", ip="192.0.2.50")
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_the_duplicate_message_points_at_the_port(self):
		doc = self.settings()
		self.add(doc, "door-a", ip="192.0.2.50")
		self.add(doc, "door-b", ip="192.0.2.50")
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.save()
		self.assertIn("port", str(caught.exception).lower())

	def test_two_machines_behind_one_address_are_fine_on_different_ports(self):
		# The office router forwards 4370 to the front door and 4371 to the back.
		doc = self.settings()
		self.add(doc, "front-door", ip="203.0.113.7")
		doc.devices[-1].port = 4370
		self.add(doc, "back-door", ip="203.0.113.7")
		doc.devices[-1].port = 4371
		doc.save()
		self.assertEqual([row.port for row in doc.devices], [4370, 4371])

	def test_the_same_address_and_port_written_with_spaces_is_still_a_duplicate(self):
		doc = self.settings()
		self.add(doc, "door-a", ip="192.0.2.50")
		self.add(doc, "door-b", ip="  192.0.2.50  ")
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_a_blank_port_counts_as_the_standard_one(self):
		# One row left empty and one set to 4370 are the same machine.
		doc = self.settings()
		self.add(doc, "door-a", ip="192.0.2.50")
		self.add(doc, "door-b", ip="192.0.2.50")
		doc.devices[-1].port = 4370
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_a_device_password_is_never_handed_back_in_plain_text(self):
		doc = self.settings()
		self.add(doc, "front-door")
		doc.devices[0].device_password = "1234"
		doc.save()

		reloaded = frappe.get_doc(SETTINGS)
		self.assertNotEqual(reloaded.devices[0].device_password, "1234")
		self.assertEqual(reloaded.devices[0].get_password("device_password"), "1234")

	def test_installing_leaves_the_shift_mapping_as_an_empty_list(self):
		# Never null: the collector reads this field on every run, and a null
		# would make the form show an empty box that looks broken. Asserting on
		# whatever the site happens to hold would fail the moment somebody
		# configured a real mapping, so drive the install helper instead.
		from nexus_zkt_integration.install import create_settings

		before = frappe.db.get_single_value(SETTINGS, "shift_type_device_mapping")
		try:
			frappe.db.set_single_value(SETTINGS, "shift_type_device_mapping", None)
			create_settings()
			self.assertEqual(frappe.db.get_single_value(SETTINGS, "shift_type_device_mapping"), "[]")
		finally:
			frappe.db.set_single_value(SETTINGS, "shift_type_device_mapping", before)

	def test_a_mapping_someone_configured_is_left_alone_by_a_reinstall(self):
		from nexus_zkt_integration.install import create_settings

		mine = '[{"shift_type_name": "Day Shift", "related_device_id": ["front-door"]}]'
		before = frappe.db.get_single_value(SETTINGS, "shift_type_device_mapping")
		try:
			frappe.db.set_single_value(SETTINGS, "shift_type_device_mapping", mine)
			create_settings()
			self.assertEqual(frappe.db.get_single_value(SETTINGS, "shift_type_device_mapping"), mine)
		finally:
			frappe.db.set_single_value(SETTINGS, "shift_type_device_mapping", before)
