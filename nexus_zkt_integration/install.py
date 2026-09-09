# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt

import frappe

SETTINGS_DOCTYPE = "Nexus ZKT Settings"


def after_install():
	create_settings()
	print_next_steps()


def create_settings():
	"""Save the Single once so the workspace shortcut opens a real document.

	No example device is created on purpose. A placeholder row would be read by
	the hourly job, fail to reach an address nobody owns, and write an error to
	the activity log every hour until somebody noticed and deleted it.
	"""
	settings = frappe.get_doc(SETTINGS_DOCTYPE)
	if not settings.get("shift_type_device_mapping"):
		settings.shift_type_device_mapping = "[]"
	settings.save(ignore_permissions=True)


def print_next_steps():
	print(
		"\nNexus ZKT Integration is installed.\n"
		"  1. Open Nexus ZKT Settings and add your device: a name and its IP address.\n"
		"  2. On each Employee, fill in Attendance Device ID with that person's user\n"
		"     ID on the device. Only Active employees are read.\n"
		"  3. Press Sync Attendance Now.\n"
	)
