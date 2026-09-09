# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class NexusZKTSettings(Document):
	def validate(self):
		self.validate_unique_device_names()

	def validate_unique_device_names(self):
		"""Two rows with the same Device Name would each overwrite the other's
		Last Read, so one of them would be skipped for good."""
		seen = set()
		for row in self.get("devices") or []:
			name = (row.device_id or "").strip()
			if name in seen:
				frappe.throw(
					_(
						"Row {0}: the device name {1} is already used above. Give each device its own name."
					).format(row.idx, frappe.bold(name))
				)
			seen.add(name)


@frappe.whitelist()
def get_nexus_zkt_settings():
	frappe.only_for("System Manager")
	return frappe.get_doc("Nexus ZKT Settings")


# The sync and clear-logs entry points live in
# nexus_zkt_integration.nexus_biometric_attendance.script and are wired up
# through hooks.scheduler_events.
