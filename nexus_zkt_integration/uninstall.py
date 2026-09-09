# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt

import frappe


def before_uninstall():
	"""Drop the cached sync status.

	Redis outlives the app: leaving the key behind would make a later reinstall
	open on the progress bar of a run that happened before it was removed.
	"""
	from nexus_zkt_integration.nexus_biometric_attendance.script import AttendanceSyncService

	try:
		frappe.cache.delete_value(AttendanceSyncService.STATUS_KEY)
	except Exception:
		pass
