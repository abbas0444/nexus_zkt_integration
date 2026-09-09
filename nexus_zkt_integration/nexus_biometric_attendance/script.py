# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt

import datetime
import functools
import inspect
import json
import time

import frappe
from frappe import _
from frappe.utils import cint
from zk import ZK

SETTINGS_DOCTYPE = "Nexus ZKT Settings"
LOG_DOCTYPE = "Nexus Attendance Log"


@functools.lru_cache(maxsize=1)
def checkin_helper_takes_coordinates():
	"""Whether the installed HRMS accepts latitude/longitude on a check-in.

	Not every HRMS release has those parameters, and passing them to one that
	does not raises TypeError. Asking the signature once per process keeps the
	same code working on Frappe 15 and 16.
	"""
	from hrms.hr.doctype.employee_checkin.employee_checkin import (
		add_log_based_on_employee_field,
	)

	params = inspect.signature(add_log_based_on_employee_field).parameters
	return "latitude" in params and "longitude" in params


class AttendanceSyncService:
	"""Turn the attendance log of every ZKTeco device in Nexus ZKT Settings into
	Employee Checkin records.

	Per device:
	  1. Collect the Attendance Device IDs of Active Employees.
	  2. Pull the device log and keep only those users' punches.
	  3. Create one Employee Checkin per new punch, with log_type IN or OUT.
	"""

	PORT = 4370  # ZK SDK protocol port

	# ZKTeco "attendance state" codes carried in each punch.
	PUNCH_IN = (0, 4)  # check-in, overtime-in
	PUNCH_OUT = (1, 5)  # check-out, overtime-out
	# A device whose punch-state option is Off sends 255 (no state). IN/OUT is
	# then derived by alternating per employee, using these two limits:
	MAX_SHIFT_HOURS = 14  # an IN older than this was never closed; next punch is a new IN
	DUPLICATE_WINDOW_SECONDS = 120  # a second punch inside this window is the same event

	# Namespaced so this app can live on a site beside another ZK integration
	# without the two overwriting each other's progress.
	PROGRESS_EVENT = "nexus_zkt_sync_progress"  # realtime event the settings form listens to
	STATUS_KEY = "nexus_zkt_sync_status"  # cache key holding the state of the current / last sync
	STALE_AFTER_SECONDS = 180  # a "running" status older than this means the run died

	def __init__(self, devices, force=False, shift_type_device_mapping=None, show_progress=False):
		self.devices = devices or []
		self.force = force  # True: ignore each device's pull frequency (manual run)
		self.show_progress = show_progress  # True: push a progress bar to the browser
		self.results = []  # one-line outcomes shown to the user after a manual run
		# after self.results: a malformed mapping logs a warning from in here
		self.shift_type_device_mapping = self._parse_mapping(shift_type_device_mapping)
		self.started = None
		self.finished = None

	# ------------------------------------------------------------------
	# ENTRY POINT
	# ------------------------------------------------------------------
	def run(self):
		self.started = datetime.datetime.now()
		self._set_status(
			state="running",
			percent=1,
			description="Starting...",
			started=self.started.strftime("%H:%M:%S"),
			finished=None,
			took_seconds=None,
			error=None,
		)
		try:
			self._run_devices()
		except Exception as e:
			self.finished = datetime.datetime.now()
			self._set_status(
				state="failed",
				percent=100,
				description=str(e)[:200],
				error=str(e)[:500],
				finished=self.finished.strftime("%H:%M:%S"),
				took_seconds=self.took_seconds,
			)
			raise
		self.finished = datetime.datetime.now()
		self._set_status(
			state="done",
			percent=100,
			description="Done",
			finished=self.finished.strftime("%H:%M:%S"),
			took_seconds=self.took_seconds,
		)

	def _run_devices(self):
		pulled = {}  # device_id -> time of a successful pull in this run
		total = len(self.devices) or 1

		for index, device in enumerate(self.devices):
			# each device owns an equal slice of the progress bar
			self._slice = (index * 100.0 / total, 100.0 / total)
			last_run = device.last_run
			if last_run and not self.force:
				minutes = (datetime.datetime.now() - last_run).total_seconds() / 60
				if minutes < (device.pull_frequency or 0):
					self._log(
						f"Skipping device {device.device_id}; pull frequency not met "
						f"({minutes:.0f} of {device.pull_frequency} minutes)",
						show=True,
					)
					continue

			self._log(f"Processing device: {device.device_id} (last run {last_run})")
			self._progress(0.02, f"Device {device.device_id}: connecting to {device.ip}...")
			pull_time = datetime.datetime.now()
			if self._process_device(device):
				pulled[device.device_id] = pull_time

			device.last_run = pull_time
			device.save(ignore_permissions=True)

		self._update_shift_sync(pulled)

	@property
	def took_seconds(self):
		if not (self.started and self.finished):
			return None
		return round((self.finished - self.started).total_seconds(), 1)

	def _progress(self, fraction, description):
		"""Advance the progress bar. `fraction` is 0..1 within the current device's
		slice of the bar."""
		base, span = getattr(self, "_slice", (0, 100))
		self._set_status(percent=max(1, min(99, int(base + span * fraction))), description=description)

	def _set_status(self, **fields):
		"""Keep the state of this run in the cache (so the settings form can show it
		again after a page refresh) and, for a browser-started run, push it live.
		A cache or realtime hiccup must never break the sync."""
		try:
			status = frappe.cache.get_value(self.STATUS_KEY) or {}
			status.update(fields)
			status["lines"] = list(self.results)
			status["updated_ts"] = time.time()  # epoch: timezone-proof staleness check
			frappe.cache.set_value(self.STATUS_KEY, status, expires_in_sec=7 * 24 * 3600)
			if self.show_progress:
				# copy: the cache hands back the same dict object within a request
				frappe.publish_realtime(self.PROGRESS_EVENT, dict(status), user=frappe.session.user)
		except Exception:
			pass

	# ------------------------------------------------------------------
	# DEVICE PIPELINE
	# ------------------------------------------------------------------
	def _process_device(self, device):
		# Step 1: which device user IDs belong to an Active Employee?
		employees = self._active_employees_by_device_id()
		if not employees:
			self._log(
				f"No Active Employee has an Attendance Device ID; skipping device {device.device_id}",
				show=True,
			)
			return False
		self._log(
			f"{len(employees)} Active Employees have an Attendance Device ID: " + ", ".join(sorted(employees))
		)

		# Step 2: pull the device log and keep only those users' punches, oldest first.
		# The ZK protocol has no per-user filter, so the filter is applied here.
		all_logs = self._fetch_from_device(device)
		if all_logs is None:
			return False
		logs = sorted(
			(log for log in all_logs if str(log["user_id"]).strip() in employees),
			key=lambda log: log["timestamp"],
		)
		ignored = len(all_logs) - len(logs)
		self._log(
			f"Fetched {len(all_logs)} logs from device {device.device_id}: "
			f"{len(logs)} belong to Active Employees, {ignored} ignored (no Active Employee with that ID)",
			show=True,
		)
		self._progress(0.3, f"Device {device.device_id}: {len(all_logs)} logs fetched, {len(logs)} to check")
		if not logs:
			return True

		# Step 3: one Employee Checkin per new punch.
		existing = self._existing_checkins(set(employees.values()), logs[0]["timestamp"])
		last = {}  # employee -> (time, log_type) of the latest punch handled so far
		created = {"IN": 0, "OUT": 0, "": 0}
		already = duplicates = failed = 0
		per_user = {}

		report_every = max(1, len(logs) // 25)

		for position, log in enumerate(logs, start=1):
			if position % report_every == 0 or position == len(logs):
				self._progress(
					0.3 + 0.65 * position / len(logs),
					f"Device {device.device_id}: {position}/{len(logs)} punches checked, "
					f"{created['IN'] + created['OUT'] + created['']} check-ins created",
				)
			user_id = str(log["user_id"]).strip()
			employee = employees[user_id]
			ts = log["timestamp"]
			per_user[user_id] = per_user.get(user_id, 0) + 1

			if (employee, ts) in existing:
				last[employee] = (ts, existing[(employee, ts)])
				already += 1
				continue

			prev = last.get(employee) or self._latest_checkin_before(employee, ts)
			direction = self._resolve_direction(device, log["punch"], prev, ts)
			if direction == "DUPLICATE":
				duplicates += 1
				continue

			ok, error = self._push_to_erp(device, user_id, ts, direction)
			if ok:
				last[employee] = (ts, direction)
				created[direction] += 1
			else:
				failed += 1
				self._log(f"[ERP ERROR] {user_id} @ {ts}: {error}")

		summary = (
			f"Device {device.device_id}: {len(logs)} punches for Active Employees, "
			f"{already} already in Employee Checkin, {created['IN']} IN + {created['OUT']} OUT created"
		)
		if created[""]:
			summary += f" + {created['']} without log type"
		summary += f", {duplicates} duplicate punches ignored, {failed} rejected by HRMS"
		self._log(summary, show=True)
		self._log("Per user: " + ", ".join(f"{uid} ({count})" for uid, count in sorted(per_user.items())))

		# The device's own memory is never touched by a sync. A punch that has not
		# been matched to an Active Employee exists nowhere but the device, and a
		# sync that wipes memory has no way to give it back. Clearing is a separate,
		# deliberate action: the "Clear Device Memory" button on Nexus ZKT Settings.
		return True

	# ------------------------------------------------------------------
	# SHIFT TYPE SYNC TIME
	# ------------------------------------------------------------------
	def _parse_mapping(self, raw):
		"""shift_type_device_mapping is a JSON list of
		{"shift_type_name": "...", "related_device_id": ["...", ...]}."""
		if not raw:
			return []
		try:
			mapping = json.loads(raw) if isinstance(raw, str) else raw
		except ValueError:
			self._log("[SETTINGS WARNING] Shift Type Device Mapping is not valid JSON; ignoring it")
			return []
		return mapping if isinstance(mapping, list) else []

	def _update_shift_sync(self, pulled):
		"""Set Shift Type.last_sync_of_checkin for every mapped shift whose devices
		were all pulled successfully in this run. HRMS auto attendance only marks
		attendance for shifts that ended before this time."""
		for entry in self.shift_type_device_mapping:
			shift = entry.get("shift_type_name")
			devices = entry.get("related_device_id") or []
			if isinstance(devices, str):
				devices = [devices]
			if not shift or not devices:
				continue
			if not frappe.db.exists("Shift Type", shift):
				self._log(f"[SETTINGS WARNING] Shift Type '{shift}' in the mapping does not exist", show=True)
				continue
			if not all(d in pulled for d in devices):
				continue  # at least one of its devices was skipped or failed this run
			sync_time = min(pulled[d] for d in devices)
			frappe.db.set_value("Shift Type", shift, "last_sync_of_checkin", sync_time)
			self._log(
				f"Shift Type '{shift}': Last Sync of Checkin set to {sync_time:%Y-%m-%d %H:%M:%S}",
				show=True,
			)

	# ------------------------------------------------------------------
	# IN / OUT
	# ------------------------------------------------------------------
	def _resolve_direction(self, device, punch, prev, ts):
		"""Return "IN", "OUT", "" (leave log type empty) or "DUPLICATE" (skip punch)."""
		mode = device.punch_direction or "AUTO"
		if mode in ("IN", "OUT"):
			return mode  # device dedicated to one direction (e.g. separate entry / exit units)
		if mode == "None":
			return ""  # let the Shift Type's check-in/out rule decide

		# AUTO: trust the state the device recorded, if any.
		if punch in self.PUNCH_IN:
			return "IN"
		if punch in self.PUNCH_OUT:
			return "OUT"

		# No state from the device: alternate per employee.
		if not prev:
			return "IN"
		prev_time, prev_type = prev
		gap = (ts - prev_time).total_seconds()
		if gap <= self.DUPLICATE_WINDOW_SECONDS:
			return "DUPLICATE"
		if prev_type != "IN" or gap > self.MAX_SHIFT_HOURS * 3600:
			return "IN"
		return "OUT"

	# ------------------------------------------------------------------
	# ERPNEXT LOOKUPS / WRITES
	# ------------------------------------------------------------------
	def _active_employees_by_device_id(self):
		"""{attendance_device_id: employee name} for Active Employees."""
		rows = frappe.get_all(
			"Employee",
			filters={"status": "Active", "attendance_device_id": ["is", "set"]},
			fields=["name", "attendance_device_id"],
		)
		return {str(r.attendance_device_id).strip(): r.name for r in rows if r.attendance_device_id}

	def _existing_checkins(self, employees, since):
		"""{(employee, time): log_type} for check-ins from `since` onwards."""
		rows = frappe.get_all(
			"Employee Checkin",
			filters={"employee": ["in", sorted(employees)], "time": [">=", since]},
			fields=["employee", "time", "log_type"],
		)
		return {(r.employee, r.time): (r.log_type or "") for r in rows}

	def _latest_checkin_before(self, employee, ts):
		row = frappe.db.get_value(
			"Employee Checkin",
			{"employee": employee, "time": ["<", ts]},
			["time", "log_type"],
			order_by="time desc",
			as_dict=True,
		)
		return (row.time, row.log_type or "") if row else None

	def _push_to_erp(self, device, user_id, ts, direction):
		from hrms.hr.doctype.employee_checkin.employee_checkin import (
			add_log_based_on_employee_field,
		)

		kwargs = {
			"employee_field_value": user_id,
			"timestamp": str(ts),
			"device_id": device.device_id,
			"log_type": direction or None,
		}
		if checkin_helper_takes_coordinates():
			kwargs["latitude"] = device.latitude
			kwargs["longitude"] = device.longitude

		try:
			add_log_based_on_employee_field(**kwargs)
			return True, None
		except Exception as e:
			return False, str(e)

	# ------------------------------------------------------------------
	# DEVICE ACCESS
	# ------------------------------------------------------------------
	def _comm_key(self, device):
		"""Communication password of the device, as the int pyzk expects.

		Most devices ship without one, so an empty field means 0.
		"""
		key = device.get_password("device_password", raise_exception=False)
		if not key:
			return 0
		try:
			return int(key)
		except (TypeError, ValueError):
			self._log(f"[DEVICE WARNING] {device.device_id} - device password must be numeric, using 0")
			return 0

	def _fetch_from_device(self, device):
		# ommit_ping: pyzk otherwise shells out to `ping` before connecting, which
		# fails wherever ICMP is blocked or the ping binary is missing (containers,
		# port-forwarded devices) even though port 4370 is reachable.
		zk = ZK(device.ip, port=self.PORT, password=self._comm_key(device), timeout=10, ommit_ping=True)
		conn = None

		try:
			conn = zk.connect()
			conn.disable_device()
			logs = conn.get_attendance()
			return [log.__dict__ for log in logs]

		except Exception as e:
			self._log(
				f"[DEVICE ERROR] {device.device_id} - {e} "
				f"(connecting to {device.ip}:{self.PORT} from this server)",
				show=True,
			)
			return None

		finally:
			if conn:
				try:
					conn.enable_device()
					conn.disconnect()
				except Exception:
					# The pull already succeeded or already failed; a device that drops
					# the socket while we tidy up must not turn that into an error.
					pass

	def _clear_device(self, device):
		"""Wipe the device's own attendance memory.

		Destructive and irreversible: the punches live nowhere else until a sync has
		copied them into Employee Checkin. Only ever called from the "Clear Device
		Memory" button, which asks the person to type the Device ID first.
		"""
		self._log("Clearing device: " + device.device_id)
		conn = None
		try:
			zk = ZK(
				device.ip,
				port=self.PORT,
				password=self._comm_key(device),
				timeout=10,
				ommit_ping=True,
			)
			conn = zk.connect()
			conn.clear_attendance()
			self._log(f"Device {device.device_id}: attendance memory cleared", show=True)
		except Exception as e:
			self._log(f"[CLEAR FAILED] {device.device_id} - {e}", show=True)
		finally:
			if conn:
				try:
					conn.disconnect()
				except Exception:
					pass

	# ------------------------------------------------------------------
	# LOGGING
	# ------------------------------------------------------------------
	def _log(self, msg, show=False):
		print(msg)
		if show:
			self.results.append(msg)
		frappe.get_doc(
			{
				"doctype": LOG_DOCTYPE,
				"log_entry": msg,
				"log_time": datetime.datetime.now(),
			}
		).insert(ignore_permissions=True)


# ----------------------------------------------------------------------
# PUBLIC ENTRY POINTS (Scheduler / Button / bench execute)
# ----------------------------------------------------------------------
@frappe.whitelist()
def clear_logs():
	""" "Clear Logs" button on the Nexus Attendance Log list, and the weekly job.
	Plain SQL: this is a log table, no hooks or per-row deletes needed."""
	frappe.only_for("System Manager")
	count = frappe.db.count(LOG_DOCTYPE)
	frappe.db.sql("DELETE FROM `tabNexus Attendance Log`")
	# No explicit commit: the request (button) and the job runner (weekly) both
	# commit on success, and committing here would end a caller's transaction.
	return {"deleted": count}


def get_status():
	"""State of the current or last sync. A run that stopped reporting progress
	for STALE_AFTER_SECONDS (process killed, request timed out) is reported as failed."""
	status = frappe.cache.get_value(AttendanceSyncService.STATUS_KEY) or {}
	if status.get("state") == "running":
		age = time.time() - (status.get("updated_ts") or 0)
		if age > AttendanceSyncService.STALE_AFTER_SECONDS:
			status["state"] = "failed"
			status["error"] = "The sync stopped without finishing (no progress for 3 minutes)."
			status["description"] = status["error"]
			frappe.cache.set_value(AttendanceSyncService.STATUS_KEY, status, expires_in_sec=7 * 24 * 3600)
	return status


@frappe.whitelist()
def get_sync_status():
	"""Polled by the Nexus ZKT Settings form on load / refresh."""
	frappe.only_for("System Manager")
	return get_status()


@frappe.whitelist()
def sync_attendance_log_to_erpnext(force=False):
	"""Pull every device in Nexus ZKT Settings into Employee Checkin and return the outcome.

	Used by the scheduler (hourly_long, respects each device's pull frequency),
	by `bench execute`, and by the "Sync Attendance Now" button on Nexus ZKT
	Settings (force=1: runs every device right now, the request waits until it
	is done).
	"""
	frappe.only_for("System Manager")
	status = get_status()
	if status.get("state") == "running":
		frappe.throw(
			_("A sync is already running (started at {0}). Wait for it to finish.").format(
				status.get("started")
			)
		)

	settings = frappe.get_doc(SETTINGS_DOCTYPE)
	service = AttendanceSyncService(
		devices=settings.get("devices") or [],
		force=cint(force),
		shift_type_device_mapping=settings.get("shift_type_device_mapping"),
		show_progress=bool(getattr(frappe.local, "request", None)),  # only for a browser call
	)
	service.run()
	return {
		"lines": service.results,
		"started": service.started.strftime("%H:%M:%S"),
		"finished": service.finished.strftime("%H:%M:%S"),
		"took_seconds": service.took_seconds,
	}


def scheduled_sync():
	"""Entry point for the scheduler (hooks.scheduler_events, hourly_long).

	Frappe's scheduler enqueues this on the "long" queue, so it already runs in a
	background worker. Unlike the button, an overlapping run is skipped quietly
	instead of raising, so the Scheduled Job Log does not fill with failures.
	"""
	status = get_status()
	if status.get("state") == "running":
		frappe.get_doc(
			{
				"doctype": LOG_DOCTYPE,
				"log_entry": (
					f"Scheduled sync skipped: a sync is already running (started at {status.get('started')})"
				),
				"log_time": datetime.datetime.now(),
			}
		).insert(ignore_permissions=True)
		return
	sync_attendance_log_to_erpnext()


@frappe.whitelist()
def clear_device_logs(device_id):
	"""Wipe one device's attendance memory from the Nexus ZKT Settings form."""
	frappe.only_for("System Manager")
	settings = frappe.get_doc(SETTINGS_DOCTYPE)
	device = None
	for d in settings.get("devices") or []:
		if d.device_id == device_id:
			device = d
			break
	if not device:
		frappe.throw(_("Device not found: {0}").format(device_id))

	service = AttendanceSyncService(devices=[device])
	service._clear_device(device)
	return {"lines": service.results}
