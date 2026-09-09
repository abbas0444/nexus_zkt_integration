# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

DEFAULT_PORT = 4370


class NexusZKTSettings(Document):
	def validate(self):
		self.validate_unique_device_names()
		self.validate_one_row_per_machine()

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

	def validate_one_row_per_machine(self):
		"""Two rows with the same address and port are one machine listed twice.

		Reading it under two names does the work twice and files the punches
		under whichever name came first, which looks like the other door has
		stopped working. Two real machines on one public address are told apart
		by the port, so that is what the message points at.
		"""
		seen = {}
		for row in self.get("devices") or []:
			where = ((row.ip or "").strip(), cint(row.port) or DEFAULT_PORT)
			if not where[0]:
				continue
			if where in seen:
				frappe.throw(
					_(
						"Row {0}: {1} already uses address {2} on port {3}. Two devices cannot "
						"share an address and a port - give this one its own address, or the "
						"port your router forwards to it."
					).format(row.idx, frappe.bold(seen[where]), frappe.bold(where[0]), where[1])
				)
			seen[where] = row.device_id


@frappe.whitelist()
def get_nexus_zkt_settings():
	frappe.only_for("System Manager")
	return frappe.get_doc("Nexus ZKT Settings")


# Reading the machines is not this document's job. The entry points live in
# nexus_zkt_integration.nexus_biometric_attendance.api and are wired to the
# scheduler through hooks.scheduler_events.
