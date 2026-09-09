"""More than one door.

A person walks in the front and out the back, so their day is spread across
machines. Deciding which punch is an arrival while looking at one machine's log
gets the second half of the day backwards, so the collector merges every
machine's punches into one stream before it decides anything. These pin that.

Employee Checkin writing is stubbed out: what is under test is the order the
punches are considered in and the direction each one is given, not HRMS.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from nexus_zkt_integration.nexus_biometric_attendance.collector import Collector, Take
from nexus_zkt_integration.nexus_biometric_attendance.punch import NO_OPINION, Punch
from nexus_zkt_integration.nexus_biometric_attendance.reader import (
	DEFAULT_ZK_PORT,
	device_port,
)

STAFF = {"501": "HR-EMP-TEST-01", "502": "HR-EMP-TEST-02"}


def door(name, direction="AUTO", ip="192.0.2.10", port=None):
	return frappe._dict(
		device_id=name,
		ip=ip,
		port=port,
		punch_direction=direction,
		pull_frequency=60,
		last_run=None,
		latitude=0,
		longitude=0,
	)


def punch(user_id, hour, minute=0, state=NO_OPINION):
	import datetime

	return Punch(user_id=user_id, at=datetime.datetime(2026, 4, 6, hour, minute), state=state)


class DoorFixture(FrappeTestCase):
	def run_over(self, *doors_and_punches):
		"""Feed the collector one Take per door and capture what it decided.

		Returns [(device name, "HH:MM", direction)] in the order written.
		"""
		takes = [
			Take(device=device, read_at=None, punches=list(punches)) for device, punches in doors_and_punches
		]
		run = Collector(devices=[take.device for take in takes])
		written = []

		run._already_recorded = lambda employees, since: {}
		run._last_reading_before = lambda employee, moment: None

		def capture(device, a_punch, direction):
			written.append((device.device_id, a_punch.at.strftime("%H:%M"), direction))
			return True, None

		run._store = capture
		run._record(takes, STAFF)
		return written


class TestTwoDoorsOneDay(DoorFixture):
	def test_a_day_across_two_doors_alternates_in_time_order(self):
		# In the front at nine, out the back at one, back in the front at two,
		# home out the back at six. Per-machine this reads 09:00 IN, 14:00 OUT
		# on the front and 13:00, 18:00 on the back, and gets both wrong.
		written = self.run_over(
			(door("front"), [punch("501", 9), punch("501", 14)]),
			(door("back"), [punch("501", 13), punch("501", 18)]),
		)
		self.assertEqual([row[2] for row in written], ["IN", "OUT", "IN", "OUT"])
		self.assertEqual([row[1] for row in written], ["09:00", "13:00", "14:00", "18:00"])

	def test_the_door_each_punch_came_through_is_kept(self):
		written = self.run_over(
			(door("front"), [punch("501", 9), punch("501", 14)]),
			(door("back"), [punch("501", 13), punch("501", 18)]),
		)
		self.assertEqual([row[0] for row in written], ["front", "back", "front", "back"])

	def test_the_order_the_doors_are_listed_in_makes_no_difference(self):
		forwards = self.run_over(
			(door("front"), [punch("501", 9), punch("501", 14)]),
			(door("back"), [punch("501", 13), punch("501", 18)]),
		)
		backwards = self.run_over(
			(door("back"), [punch("501", 13), punch("501", 18)]),
			(door("front"), [punch("501", 9), punch("501", 14)]),
		)
		self.assertEqual(forwards, backwards)

	def test_three_doors_still_read_as_one_day(self):
		written = self.run_over(
			(door("front"), [punch("501", 8), punch("501", 16)]),
			(door("back"), [punch("501", 12)]),
			(door("side"), [punch("501", 13), punch("501", 19)]),
		)
		self.assertEqual([row[2] for row in written], ["IN", "OUT", "IN", "OUT", "IN"])

	def test_two_people_through_the_same_doors_do_not_affect_each_other(self):
		written = self.run_over(
			(door("front"), [punch("501", 9), punch("502", 10)]),
			(door("back"), [punch("502", 17), punch("501", 18)]),
		)
		# 501 in at nine and out at six; 502 in at ten and out at five. Each
		# person alternates on their own, whichever door they happened to use.
		self.assertEqual([row[2] for row in written], ["IN", "IN", "OUT", "OUT"])
		self.assertEqual([row[1] for row in written], ["09:00", "10:00", "17:00", "18:00"])


class TestDoorsWithAFixedDirection(DoorFixture):
	def test_an_entry_door_and_an_exit_door_keep_their_own_setting(self):
		written = self.run_over(
			(door("front", "IN"), [punch("501", 9), punch("501", 14)]),
			(door("back", "OUT"), [punch("501", 13), punch("501", 18)]),
		)
		self.assertEqual([row[2] for row in written], ["IN", "OUT", "IN", "OUT"])

	def test_a_fixed_door_beside_an_automatic_one_does_not_confuse_it(self):
		written = self.run_over(
			(door("front", "IN"), [punch("501", 9)]),
			(door("back", "AUTO"), [punch("501", 18)]),
		)
		self.assertEqual([row[2] for row in written], ["IN", "OUT"])


class TestTheSamePersonOnTwoDoorsAtOnce(DoorFixture):
	def test_a_second_door_a_minute_later_is_the_same_arrival(self):
		# Walking through a lobby past two readers is one arrival, not an
		# arrival and a departure a minute apart.
		written = self.run_over(
			(door("front"), [punch("501", 9, 0)]),
			(door("back"), [punch("501", 9, 1)]),
		)
		self.assertEqual(len(written), 1)

	def test_two_doors_at_the_very_same_instant_store_one_check_in(self):
		written = self.run_over(
			(door("front"), [punch("501", 9)]),
			(door("back"), [punch("501", 9)]),
		)
		self.assertEqual(len(written), 1)


class TestNothingToDo(DoorFixture):
	def test_doors_that_held_no_punches_are_still_reported(self):
		written = self.run_over((door("front"), []), (door("back"), []))
		self.assertEqual(written, [])
		self.assertTrue(
			frappe.db.exists("Nexus Attendance Log", {"log_entry": ["like", "front:%"]}),
			"a door with nothing on it should still say so",
		)


class TestWhichPortToKnockOn(FrappeTestCase):
	def test_an_empty_port_means_the_standard_one(self):
		self.assertEqual(device_port(door("front")), DEFAULT_ZK_PORT)
		self.assertEqual(device_port(door("front", port=0)), DEFAULT_ZK_PORT)

	def test_a_port_on_the_row_is_used(self):
		# Two machines behind one office router are told apart this way.
		self.assertEqual(device_port(door("back", port=4371)), 4371)

	def test_a_port_written_as_text_still_works(self):
		self.assertEqual(device_port(door("back", port="4372")), 4372)
