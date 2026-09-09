"""The decisions the sync makes, checked without a device in the room.

Everything here is pure logic over a fake device row and fake punches, so it
runs the same on Frappe 15 and 16 and needs no ZKTeco hardware.
"""

import datetime
import time

import frappe
from frappe.tests.utils import FrappeTestCase

from nexus_zkt_integration.nexus_biometric_attendance.script import (
	AttendanceSyncService,
	checkin_helper_takes_coordinates,
	clear_logs,
	get_status,
)

NO_STATE = 255  # what a device sends when its punch-state option is off


def device(**overrides):
	row = frappe._dict(
		device_id="front-door",
		ip="192.0.2.10",
		punch_direction="AUTO",
		pull_frequency=60,
		last_run=None,
		latitude=0,
		longitude=0,
	)
	row.update(overrides)
	return row


def service(**kwargs):
	return AttendanceSyncService(devices=[], **kwargs)


class TestPunchDirection(FrappeTestCase):
	def setUp(self):
		self.svc = service()
		self.now = datetime.datetime(2026, 9, 9, 9, 0, 0)

	def resolve(self, punch=NO_STATE, prev=None, ts=None, **dev):
		return self.svc._resolve_direction(device(**dev), punch, prev, ts or self.now)

	# --- the device tells us ------------------------------------------------
	def test_device_state_0_is_a_check_in(self):
		self.assertEqual(self.resolve(punch=0), "IN")

	def test_device_state_4_is_an_overtime_check_in(self):
		self.assertEqual(self.resolve(punch=4), "IN")

	def test_device_state_1_is_a_check_out(self):
		self.assertEqual(self.resolve(punch=1), "OUT")

	def test_device_state_5_is_an_overtime_check_out(self):
		self.assertEqual(self.resolve(punch=5), "OUT")

	# --- the device is set to one direction ---------------------------------
	def test_an_in_only_device_overrides_the_punch_state(self):
		self.assertEqual(self.resolve(punch=1, punch_direction="IN"), "IN")

	def test_an_out_only_device_overrides_the_punch_state(self):
		self.assertEqual(self.resolve(punch=0, punch_direction="OUT"), "OUT")

	def test_none_leaves_the_log_type_empty_for_the_shift_rule_to_decide(self):
		self.assertEqual(self.resolve(punch=0, punch_direction="None"), "")

	def test_a_blank_direction_falls_back_to_auto(self):
		self.assertEqual(self.resolve(punch=0, punch_direction=None), "IN")

	# --- the device tells us nothing: alternate -----------------------------
	def test_the_first_punch_of_a_person_is_an_in(self):
		self.assertEqual(self.resolve(prev=None), "IN")

	def test_the_punch_after_an_in_is_an_out(self):
		prev = (self.now - datetime.timedelta(hours=8), "IN")
		self.assertEqual(self.resolve(prev=prev), "OUT")

	def test_the_punch_after_an_out_is_an_in(self):
		prev = (self.now - datetime.timedelta(hours=8), "OUT")
		self.assertEqual(self.resolve(prev=prev), "IN")

	def test_a_second_punch_within_two_minutes_is_the_same_press_twice(self):
		prev = (self.now - datetime.timedelta(seconds=90), "IN")
		self.assertEqual(self.resolve(prev=prev), "DUPLICATE")

	def test_just_past_the_duplicate_window_counts_as_a_real_punch(self):
		prev = (self.now - datetime.timedelta(seconds=121), "IN")
		self.assertEqual(self.resolve(prev=prev), "OUT")

	def test_exactly_on_the_duplicate_window_is_still_a_duplicate(self):
		prev = (self.now - datetime.timedelta(seconds=120), "IN")
		self.assertEqual(self.resolve(prev=prev), "DUPLICATE")

	def test_an_in_left_open_overnight_does_not_swallow_the_next_morning(self):
		# 15 hours is past MAX_SHIFT_HOURS: the person forgot to punch out, so the
		# next punch has to start a new day rather than close yesterday.
		prev = (self.now - datetime.timedelta(hours=15), "IN")
		self.assertEqual(self.resolve(prev=prev), "IN")

	def test_an_in_still_inside_the_shift_window_closes_normally(self):
		prev = (self.now - datetime.timedelta(hours=13, minutes=59), "IN")
		self.assertEqual(self.resolve(prev=prev), "OUT")

	def test_a_previous_punch_with_no_log_type_starts_a_fresh_in(self):
		prev = (self.now - datetime.timedelta(hours=3), "")
		self.assertEqual(self.resolve(prev=prev), "IN")


class TestShiftMapping(FrappeTestCase):
	def test_a_json_string_is_read(self):
		svc = service(shift_type_device_mapping='[{"shift_type_name": "Day", "related_device_id": ["a"]}]')
		self.assertEqual(svc.shift_type_device_mapping[0]["shift_type_name"], "Day")

	def test_an_already_parsed_list_is_accepted(self):
		svc = service(shift_type_device_mapping=[{"shift_type_name": "Day"}])
		self.assertEqual(len(svc.shift_type_device_mapping), 1)

	def test_nothing_configured_means_no_mapping(self):
		self.assertEqual(service(shift_type_device_mapping=None).shift_type_device_mapping, [])
		self.assertEqual(service(shift_type_device_mapping="").shift_type_device_mapping, [])

	def test_broken_json_is_ignored_instead_of_stopping_the_sync(self):
		svc = service(shift_type_device_mapping="{not json")
		self.assertEqual(svc.shift_type_device_mapping, [])

	def test_broken_json_says_so_in_the_activity_log(self):
		service(shift_type_device_mapping="{not json")
		self.assertTrue(
			frappe.db.exists("Nexus Attendance Log", {"log_entry": ["like", "%not valid JSON%"]}),
			"a malformed mapping should leave a line in the activity log",
		)

	def test_a_json_object_is_not_a_mapping_list(self):
		self.assertEqual(service(shift_type_device_mapping='{"a": 1}').shift_type_device_mapping, [])


class TestHRMSCompatibility(FrappeTestCase):
	def test_the_coordinate_probe_matches_the_installed_hrms(self):
		import inspect

		from hrms.hr.doctype.employee_checkin.employee_checkin import (
			add_log_based_on_employee_field,
		)

		params = inspect.signature(add_log_based_on_employee_field).parameters
		self.assertEqual(
			checkin_helper_takes_coordinates(),
			"latitude" in params and "longitude" in params,
		)

	def test_the_probe_answers_yes_or_no_and_nothing_else(self):
		self.assertIn(checkin_helper_takes_coordinates(), (True, False))


class TestRunStatus(FrappeTestCase):
	def tearDown(self):
		frappe.cache.delete_value(AttendanceSyncService.STATUS_KEY)

	def test_no_run_yet_reports_nothing(self):
		frappe.cache.delete_value(AttendanceSyncService.STATUS_KEY)
		self.assertEqual(get_status(), {})

	def test_a_run_still_reporting_progress_is_left_alone(self):
		frappe.cache.set_value(
			AttendanceSyncService.STATUS_KEY,
			{"state": "running", "updated_ts": time.time(), "percent": 40},
		)
		self.assertEqual(get_status()["state"], "running")

	def test_a_run_that_went_quiet_is_reported_as_failed_not_stuck(self):
		# A killed worker leaves "running" in the cache forever, and the form would
		# show a progress bar that never moves and refuse to start a new sync.
		frappe.cache.set_value(
			AttendanceSyncService.STATUS_KEY,
			{
				"state": "running",
				"updated_ts": time.time() - AttendanceSyncService.STALE_AFTER_SECONDS - 1,
			},
		)
		status = get_status()
		self.assertEqual(status["state"], "failed")
		self.assertIn("without finishing", status["error"])

	def test_a_finished_run_keeps_its_result(self):
		frappe.cache.set_value(
			AttendanceSyncService.STATUS_KEY, {"state": "done", "updated_ts": 0, "percent": 100}
		)
		self.assertEqual(get_status()["state"], "done")


class TestActivityLog(FrappeTestCase):
	def test_a_logged_line_is_stored_and_shown_when_asked(self):
		svc = service()
		svc._log("quiet line")
		svc._log("headline", show=True)
		self.assertEqual(svc.results, ["headline"])
		self.assertTrue(frappe.db.exists("Nexus Attendance Log", {"log_entry": "quiet line"}))

	def test_clear_logs_empties_the_table_and_counts_what_it_removed(self):
		service()._log("about to be cleared")
		before = frappe.db.count("Nexus Attendance Log")
		self.assertGreater(before, 0)
		self.assertEqual(clear_logs()["deleted"], before)
		self.assertEqual(frappe.db.count("Nexus Attendance Log"), 0)


class TestEmployeeLookup(FrappeTestCase):
	def test_only_active_employees_with_a_device_id_are_collected(self):
		found = service()._active_employees_by_device_id()
		self.assertIsInstance(found, dict)
		for device_id, employee in found.items():
			self.assertEqual(frappe.db.get_value("Employee", employee, "status"), "Active")
			self.assertEqual(device_id, device_id.strip())
