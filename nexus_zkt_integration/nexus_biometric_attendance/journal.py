# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt

"""What a run wrote down, and how far along it is.

Two separate concerns that both outlive the run itself: the permanent record in
Nexus Attendance Log, and the live progress the settings form draws.
"""

import time
from datetime import datetime

import frappe

LOG_DOCTYPE = "Nexus Attendance Log"

# Namespaced so a site running a second attendance app does not end up with the
# two overwriting each other's progress.
PROGRESS_EVENT = "nexus_zkt_sync_progress"
STATUS_CACHE_KEY = "nexus_zkt_sync_status"

# A run that has not reported progress for this long is not running any more:
# the worker was killed, or the request gave up. Saying so beats a bar that
# never moves and a button that refuses to start anything new.
SILENCE_MEANS_DEAD = 180
STATUS_KEEPS_FOR = 7 * 24 * 3600

IDLE, RUNNING, FINISHED, BROKEN = "idle", "running", "done", "failed"


class Journal:
	"""The written record of one run.

	Every line lands in Nexus Attendance Log. Lines marked `notable` are also
	handed back to whoever pressed the button, because a wall of detail helps
	nobody read the one sentence that mattered.
	"""

	def __init__(self):
		self.notable = []

	def write(self, sentence, notable=False):
		print(sentence)
		if notable:
			self.notable.append(sentence)
		frappe.get_doc(
			{
				"doctype": LOG_DOCTYPE,
				"log_entry": sentence,
				"log_time": datetime.now(),
			}
		).insert(ignore_permissions=True)

	def warn(self, sentence):
		self.write(f"[WARNING] {sentence}", notable=True)

	def problem(self, sentence):
		self.write(f"[PROBLEM] {sentence}", notable=True)

	def refusal(self, sentence):
		"""HRMS declined to store a punch. Detail, not headline."""
		self.write(f"[REFUSED] {sentence}")

	@staticmethod
	def clear():
		"""Empty the whole table.

		Plain SQL: it is a log, with no hooks worth firing and no reason to load
		thousands of documents to throw them away. No commit either - the
		request and the scheduler both commit on success, and committing here
		would close a transaction belonging to whoever called.
		"""
		emptied = frappe.db.count(LOG_DOCTYPE)
		frappe.db.sql("DELETE FROM `tabNexus Attendance Log`")
		return emptied


class RunStatus:
	"""How far along the current run is, readable after a page refresh.

	Kept in the cache rather than a document: it is worth nothing an hour later,
	and a run that writes its progress to the database several times a second
	would be writing more than it reads.
	"""

	def __init__(self, live=False):
		self.live = live  # push to the browser as well as store
		self.started_at = None
		self.ended_at = None

	def begin(self):
		self.started_at = datetime.now()
		self._store(
			state=RUNNING,
			percent=1,
			description="Starting...",
			started=self.started_at.strftime("%H:%M:%S"),
			finished=None,
			took_seconds=None,
			error=None,
		)

	def advance(self, percent, description):
		self._store(state=RUNNING, percent=max(1, min(99, int(percent))), description=description)

	def finish(self, journal):
		self.ended_at = datetime.now()
		self._store(
			state=FINISHED,
			percent=100,
			description="Finished",
			finished=self.ended_at.strftime("%H:%M:%S"),
			took_seconds=self.seconds_taken,
			lines=list(journal.notable),
		)

	def fail(self, error, journal):
		self.ended_at = datetime.now()
		self._store(
			state=BROKEN,
			percent=100,
			description=str(error)[:200],
			error=str(error)[:500],
			finished=self.ended_at.strftime("%H:%M:%S"),
			took_seconds=self.seconds_taken,
			lines=list(journal.notable),
		)

	@property
	def seconds_taken(self):
		if not (self.started_at and self.ended_at):
			return None
		return round((self.ended_at - self.started_at).total_seconds(), 1)

	def _store(self, **fields):
		"""Neither the cache nor the socket is allowed to break a sync."""
		try:
			snapshot = read_status() or {}
			snapshot.update(fields)
			snapshot["updated_ts"] = time.time()  # epoch: no timezone to get wrong
			frappe.cache.set_value(STATUS_CACHE_KEY, snapshot, expires_in_sec=STATUS_KEEPS_FOR)
			if self.live:
				# a copy: within one request the cache hands back the same object
				frappe.publish_realtime(PROGRESS_EVENT, dict(snapshot), user=frappe.session.user)
		except Exception:
			pass

	@staticmethod
	def forget():
		try:
			frappe.cache.delete_value(STATUS_CACHE_KEY)
		except Exception:
			pass


def read_status():
	"""Read the stored snapshot.

	`expires=True` is not optional. This key is written with an expiry, and on
	Frappe 15 a key written that way is never put in frappe.local.cache - while
	a *miss* on an ordinary read is. Read the key once before the first write
	and None gets pinned locally for the rest of the request, so every later
	read returns None however many times it has been written since. The progress
	bar would never move, and the guard against two overlapping runs would never
	see the run that is already going.
	"""
	return frappe.cache.get_value(STATUS_CACHE_KEY, expires=True)


def current_status():
	"""What the settings form should draw right now.

	A run still claiming to be alive after SILENCE_MEANS_DEAD seconds without a
	word is reported as broken, and the correction is written back so the next
	caller does not have to work it out again.
	"""
	snapshot = read_status() or {}
	if snapshot.get("state") != RUNNING:
		return snapshot

	silent_for = time.time() - (snapshot.get("updated_ts") or 0)
	if silent_for <= SILENCE_MEANS_DEAD:
		return snapshot

	snapshot["state"] = BROKEN
	snapshot["error"] = "The sync stopped without finishing (no progress for 3 minutes)."
	snapshot["description"] = snapshot["error"]
	try:
		frappe.cache.set_value(STATUS_CACHE_KEY, snapshot, expires_in_sec=STATUS_KEEPS_FOR)
	except Exception:
		pass
	return snapshot


def a_run_is_under_way():
	return current_status().get("state") == RUNNING
