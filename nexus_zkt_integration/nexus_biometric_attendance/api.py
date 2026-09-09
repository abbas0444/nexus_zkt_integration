# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt

"""Everything that can start a run: the button, the scheduler, the shell."""

import frappe
from frappe import _

from .collector import Collector
from .journal import Journal, RunStatus, a_run_is_under_way, current_status
from .reader import DeviceUnreachable, erase_punches

SETTINGS_DOCTYPE = "Nexus ZKT Settings"


def _settings():
	return frappe.get_doc(SETTINGS_DOCTYPE)


def _started_from_a_browser():
	return bool(getattr(frappe.local, "request", None))


@frappe.whitelist()
def collect_now(force=False):
	"""Read every machine and store what is new.

	Used by the Sync Attendance Now button (force=1: every machine, right now,
	and the request waits for the answer) and by `bench execute`.
	"""
	frappe.only_for("System Manager")

	if a_run_is_under_way():
		frappe.throw(
			_("A sync is already running (started at {0}). Wait for it to finish.").format(
				current_status().get("started")
			)
		)

	settings = _settings()
	run = Collector(
		devices=settings.get("devices") or [],
		ignore_wait=frappe.utils.cint(force),
		shift_map=settings.get("shift_type_device_mapping"),
		live=_started_from_a_browser(),
	)
	return run.collect()


def scheduled_collection():
	"""The hourly job, wired up in hooks.scheduler_events.

	The scheduler puts this on the long queue, so it is already in a worker.
	Unlike the button it steps aside quietly when a run is in progress: raising
	would fill the Scheduled Job Log with failures that are not failures.
	"""
	if a_run_is_under_way():
		Journal().write(
			f"The hourly read was skipped: a sync started at "
			f"{current_status().get('started')} is still going."
		)
		return
	collect_now()


@frappe.whitelist()
def sync_status():
	"""Polled by the settings form on load and while a run is going."""
	frappe.only_for("System Manager")
	return current_status()


@frappe.whitelist()
def purge_journal():
	"""The Clear Logs button, and the weekly tidy-up."""
	frappe.only_for("System Manager")
	return {"deleted": Journal.clear()}


@frappe.whitelist()
def erase_device(device_id):
	"""Wipe one machine's memory.

	Destructive and impossible to undo: until a run has copied them, the punches
	are nowhere else. The form makes the person pick the machine and type its
	name back before this is called.
	"""
	frappe.only_for("System Manager")

	chosen = None
	for device in _settings().get("devices") or []:
		if device.device_id == device_id:
			chosen = device
			break
	if not chosen:
		frappe.throw(_("There is no device called {0}.").format(device_id))

	journal = Journal()
	try:
		erase_punches(chosen, on_warning=journal.warn)
		journal.write(f"The memory of {device_id} was erased on request.", notable=True)
	except DeviceUnreachable as unreachable:
		journal.problem(str(unreachable))
	except Exception as trouble:
		journal.problem(f"{device_id} could not be erased - {trouble}")

	return {"lines": journal.notable}


def forget_status():
	"""Called when the app is removed; Redis outlives it."""
	RunStatus.forget()
