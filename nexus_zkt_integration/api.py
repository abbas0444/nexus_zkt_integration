# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt

import frappe


def has_app_permission():
	"""Whether to show the app's tile on the /apps screen.

	The whole app is System Manager territory: it holds device IP addresses and
	communication keys, and it writes Employee Checkin records for everyone.
	"""
	return "System Manager" in frappe.get_roles()
