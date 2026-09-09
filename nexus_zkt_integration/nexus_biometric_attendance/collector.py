# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt

"""One run: read every machine, write what is new into Employee Checkin."""

import functools
import inspect
import json
from datetime import datetime

import frappe

from .journal import Journal, RunStatus
from .punch import REPEAT, DirectionRule, Reading, Tally
from .reader import DeviceUnreachable, read_punches

STAFF_DOCTYPE = "Employee"
CHECKIN_DOCTYPE = "Employee Checkin"
SHIFT_DOCTYPE = "Shift Type"

# Share of one machine's slice of the progress bar spent before the punches are
# in hand. Reading the machine is the slow part; writing is quick.
READING_SHARE = 0.3
WRITING_SHARE = 0.65
PROGRESS_REPORTS_PER_DEVICE = 25


@functools.lru_cache(maxsize=1)
def checkin_helper_takes_coordinates():
	"""Whether the installed HRMS will accept a latitude and longitude.

	Not every release of that helper has them, and handing them to one that does
	not raises TypeError on every single punch. Asking the signature once a
	process keeps one copy of this app working on Frappe 15 and 16 alike.
	"""
	from hrms.hr.doctype.employee_checkin.employee_checkin import (
		add_log_based_on_employee_field,
	)

	accepted = inspect.signature(add_log_based_on_employee_field).parameters
	return "latitude" in accepted and "longitude" in accepted


def parse_shift_map(raw, journal=None):
	"""Read the Shift Type Device Mapping field.

	Hand-written JSON in a text box is going to be wrong sometimes. A mistake
	there costs the site its auto-attendance timestamps, which is bad, but
	refusing to read any machine at all would be worse - so say so and carry on.
	"""
	if not raw:
		return []
	try:
		parsed = json.loads(raw) if isinstance(raw, str) else raw
	except ValueError:
		if journal:
			journal.warn("The Shift Type Device Mapping is not valid JSON, so it was skipped.")
		return []
	return parsed if isinstance(parsed, list) else []


class Collector:
	def __init__(self, devices, ignore_wait=False, shift_map=None, live=False):
		self.devices = list(devices or [])
		self.ignore_wait = ignore_wait  # a person pressed the button; do not make them wait
		self.journal = Journal()
		self.status = RunStatus(live=live)
		self.shift_map = parse_shift_map(shift_map, self.journal)
		self._slice_start = 0.0
		self._slice_width = 100.0

	# ------------------------------------------------------------------
	# the run
	# ------------------------------------------------------------------
	def collect(self):
		self.status.begin()
		try:
			read_at = self._visit_every_device()
		except Exception as trouble:
			self.status.fail(trouble, self.journal)
			raise
		self._advance_shift_types(read_at)
		self.status.finish(self.journal)
		return self.report()

	def report(self):
		return {
			"lines": list(self.journal.notable),
			"started": self.status.started_at.strftime("%H:%M:%S") if self.status.started_at else None,
			"finished": self.status.ended_at.strftime("%H:%M:%S") if self.status.ended_at else None,
			"took_seconds": self.status.seconds_taken,
		}

	def _visit_every_device(self):
		"""Returns {device name: when it was read} for the ones that worked."""
		read_at = {}
		share = 100.0 / (len(self.devices) or 1)

		for position, device in enumerate(self.devices):
			self._slice_start, self._slice_width = position * share, share

			waited = self._wait_remaining(device)
			if waited is not None:
				self.journal.write(
					f"{device.device_id} was left alone: it is read every "
					f"{device.pull_frequency} minutes and only {waited:.0f} have passed.",
					notable=True,
				)
				continue

			started = datetime.now()
			if self._collect_one(device):
				read_at[device.device_id] = started

			device.last_run = started
			device.save(ignore_permissions=True)

		return read_at

	def _wait_remaining(self, device):
		"""Minutes elapsed since the last read, if it is too soon to read again."""
		if self.ignore_wait or not device.last_run:
			return None
		elapsed = (datetime.now() - device.last_run).total_seconds() / 60
		return elapsed if elapsed < (device.pull_frequency or 0) else None

	def _collect_one(self, device):
		staff = self._staff_by_device_id()
		if not staff:
			self.journal.problem(
				f"{device.device_id} was skipped: nobody active has an Attendance Device ID yet. "
				"Fill that field on each Employee with their user number on the machine."
			)
			return False

		self._show(0.02, f"{device.device_id}: connecting to {device.ip}")
		try:
			everything = read_punches(device, on_warning=self.journal.warn)
		except DeviceUnreachable as unreachable:
			self.journal.problem(str(unreachable))
			return False

		ours = [p for p in everything if p.user_id in staff]
		strangers = len(everything) - len(ours)
		self.journal.write(
			f"{device.device_id} held {len(everything)} punches: {len(ours)} from active staff, "
			f"{strangers} from people with no matching active Employee.",
			notable=True,
		)
		self._show(READING_SHARE, f"{device.device_id}: {len(ours)} punches to check")
		if not ours:
			return True

		self._write_checkins(device, ours, staff)
		# The machine's memory is never touched by a run. A punch nobody matched
		# exists only on the device, and a read that erased it could not give it
		# back. Erasing is its own deliberate button.
		return True

	def _write_checkins(self, device, punches, staff):
		rule = DirectionRule(device.punch_direction)
		known = self._already_recorded(set(staff.values()), punches[0].at)
		latest = {}  # employee -> Reading, as this run learns it
		tally = Tally()
		per_person = {}
		report_every = max(1, len(punches) // PROGRESS_REPORTS_PER_DEVICE)

		for seen, punch in enumerate(punches, start=1):
			if seen % report_every == 0 or seen == len(punches):
				self._show(
					READING_SHARE + WRITING_SHARE * seen / len(punches),
					f"{device.device_id}: {seen} of {len(punches)} checked, {tally.stored} added",
				)

			employee = staff[punch.user_id]
			per_person[punch.user_id] = per_person.get(punch.user_id, 0) + 1

			if (employee, punch.at) in known:
				latest[employee] = Reading(punch.at, known[(employee, punch.at)])
				tally.already_known += 1
				continue

			previous = latest.get(employee) or self._last_reading_before(employee, punch.at)
			direction = rule.decide(punch, previous)
			if direction == REPEAT:
				tally.repeats += 1
				continue

			stored, refusal = self._store(device, punch, direction)
			if stored:
				latest[employee] = Reading(punch.at, direction)
				tally.count(direction)
			else:
				tally.rejected += 1
				self.journal.refusal(f"{punch.user_id} at {punch.at}: {refusal}")

		self.journal.write(tally.describe(device.device_id, len(punches)), notable=True)
		self.journal.write(
			"Punches per person - "
			+ ", ".join(f"{uid}: {count}" for uid, count in sorted(per_person.items()))
		)

	# ------------------------------------------------------------------
	# what ERPNext already knows
	# ------------------------------------------------------------------
	def _staff_by_device_id(self):
		"""{their number on the machine: Employee} for active staff only."""
		rows = frappe.get_all(
			STAFF_DOCTYPE,
			filters={"status": "Active", "attendance_device_id": ["is", "set"]},
			fields=["name", "attendance_device_id"],
		)
		return {str(r.attendance_device_id).strip(): r.name for r in rows if r.attendance_device_id}

	def _already_recorded(self, employees, from_time):
		"""{(employee, moment): direction} for check-ins at or after from_time."""
		rows = frappe.get_all(
			CHECKIN_DOCTYPE,
			filters={"employee": ["in", sorted(employees)], "time": [">=", from_time]},
			fields=["employee", "time", "log_type"],
		)
		return {(r.employee, r.time): (r.log_type or "") for r in rows}

	def _last_reading_before(self, employee, moment):
		row = frappe.db.get_value(
			CHECKIN_DOCTYPE,
			{"employee": employee, "time": ["<", moment]},
			["time", "log_type"],
			order_by="time desc",
			as_dict=True,
		)
		return Reading(row.time, row.log_type or "") if row else None

	def _store(self, device, punch, direction):
		from hrms.hr.doctype.employee_checkin.employee_checkin import (
			add_log_based_on_employee_field,
		)

		arguments = {
			"employee_field_value": punch.user_id,
			"timestamp": str(punch.at),
			"device_id": device.device_id,
			"log_type": direction or None,
		}
		if checkin_helper_takes_coordinates():
			arguments["latitude"] = device.latitude
			arguments["longitude"] = device.longitude

		try:
			add_log_based_on_employee_field(**arguments)
			return True, None
		except Exception as refusal:
			return False, str(refusal)

	# ------------------------------------------------------------------
	# telling HRMS how complete the check-ins are
	# ------------------------------------------------------------------
	def _advance_shift_types(self, read_at):
		"""Move each mapped Shift Type's Last Sync of Checkin forward.

		HRMS marks attendance automatically only up to that moment, so it must
		never run ahead of the punches. A shift whose machines were not all read
		this time is left where it was: moving it would tell HRMS a gap is
		complete when it is not.
		"""
		for entry in self.shift_map:
			shift = entry.get("shift_type_name")
			wanted = entry.get("related_device_id") or []
			if isinstance(wanted, str):
				wanted = [wanted]
			if not shift or not wanted:
				continue
			if not frappe.db.exists(SHIFT_DOCTYPE, shift):
				self.journal.warn(f"The mapping names a Shift Type that does not exist: {shift}")
				continue
			if not all(name in read_at for name in wanted):
				continue

			complete_to = min(read_at[name] for name in wanted)
			frappe.db.set_value(SHIFT_DOCTYPE, shift, "last_sync_of_checkin", complete_to)
			self.journal.write(
				f"{shift} is now complete up to {complete_to:%Y-%m-%d %H:%M:%S}.", notable=True
			)

	# ------------------------------------------------------------------
	def _show(self, fraction, description):
		"""Move the bar. `fraction` is 0..1 within the current machine's slice."""
		self.status.advance(self._slice_start + self._slice_width * fraction, description)
