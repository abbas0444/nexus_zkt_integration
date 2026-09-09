"""The settings form: what it accepts and what it refuses."""

import frappe
from frappe.tests.utils import FrappeTestCase

SETTINGS = "Nexus ZKT Settings"


class TestSettings(FrappeTestCase):
	def settings(self):
		doc = frappe.get_doc(SETTINGS)
		doc.set("devices", [])
		return doc

	def add(self, doc, device_id, ip="192.0.2.10"):
		doc.append("devices", {"device_id": device_id, "ip": ip, "punch_direction": "AUTO"})

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

	def test_a_device_password_is_never_handed_back_in_plain_text(self):
		doc = self.settings()
		self.add(doc, "front-door")
		doc.devices[0].device_password = "1234"
		doc.save()

		reloaded = frappe.get_doc(SETTINGS)
		self.assertNotEqual(reloaded.devices[0].device_password, "1234")
		self.assertEqual(reloaded.devices[0].get_password("device_password"), "1234")

	def test_the_shift_mapping_starts_empty_rather_than_null(self):
		self.assertIn(frappe.get_doc(SETTINGS).shift_type_device_mapping or "[]", ("[]", "{}"))
