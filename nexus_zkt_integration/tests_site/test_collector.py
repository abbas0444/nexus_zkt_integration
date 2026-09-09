"""The parts of a run that need a database but not a device."""

import time

import frappe
from frappe.tests.utils import FrappeTestCase

from nexus_zkt_integration.nexus_biometric_attendance.api import purge_journal
from nexus_zkt_integration.nexus_biometric_attendance.collector import (
	Collector,
	checkin_helper_takes_coordinates,
	parse_shift_map,
)
from nexus_zkt_integration.nexus_biometric_attendance.journal import (
	BROKEN,
	RUNNING,
	STATUS_CACHE_KEY,
	Journal,
	a_run_is_under_way,
	current_status,
	read_status,
)


def a_run(**kwargs):
	return Collector(devices=[], **kwargs)


class TestReadingTheShiftMapping(FrappeTestCase):
	def test_a_json_string_is_read(self):
		mapping = parse_shift_map('[{"shift_type_name": "Day", "related_device_id": ["a"]}]')
		self.assertEqual(mapping[0]["shift_type_name"], "Day")

	def test_a_list_that_is_already_parsed_is_accepted(self):
		self.assertEqual(len(parse_shift_map([{"shift_type_name": "Day"}])), 1)

	def test_an_empty_field_means_no_mapping(self):
		self.assertEqual(parse_shift_map(None), [])
		self.assertEqual(parse_shift_map(""), [])
		self.assertEqual(parse_shift_map("[]"), [])

	def test_broken_json_is_skipped_rather_than_stopping_the_run(self):
		self.assertEqual(parse_shift_map("{not json"), [])

	def test_a_json_object_is_not_a_list_of_shifts(self):
		self.assertEqual(parse_shift_map('{"a": 1}'), [])

	def test_broken_json_says_so_in_the_activity_log(self):
		a_run(shift_map="{not json")
		self.assertTrue(
			frappe.db.exists("Nexus Attendance Log", {"log_entry": ["like", "%not valid JSON%"]}),
			"a malformed mapping should leave a line someone can find",
		)

	def test_it_says_nothing_when_there_is_nothing_to_complain_about(self):
		before = frappe.db.count("Nexus Attendance Log")
		a_run(shift_map="[]")
		self.assertEqual(frappe.db.count("Nexus Attendance Log"), before)


class TestWaitingBetweenReads(FrappeTestCase):
	def device(self, minutes_ago=None, every=60):
		import datetime

		last = None
		if minutes_ago is not None:
			last = datetime.datetime.now() - datetime.timedelta(minutes=minutes_ago)
		return frappe._dict(device_id="front-door", last_run=last, pull_frequency=every)

	def test_a_machine_never_read_before_is_due(self):
		self.assertIsNone(a_run()._wait_remaining(self.device(minutes_ago=None)))

	def test_a_machine_read_a_moment_ago_is_not_due(self):
		self.assertIsNotNone(a_run()._wait_remaining(self.device(minutes_ago=5)))

	def test_a_machine_read_longer_ago_than_its_interval_is_due(self):
		self.assertIsNone(a_run()._wait_remaining(self.device(minutes_ago=90)))

	def test_pressing_the_button_ignores_the_interval(self):
		run = a_run(ignore_wait=True)
		self.assertIsNone(run._wait_remaining(self.device(minutes_ago=1)))

	def test_a_machine_with_no_interval_set_is_always_due(self):
		self.assertIsNone(a_run()._wait_remaining(self.device(minutes_ago=1, every=0)))


class TestWorkingWithTheInstalledHRMS(FrappeTestCase):
	def test_the_coordinate_probe_matches_the_real_signature(self):
		import inspect

		from hrms.hr.doctype.employee_checkin.employee_checkin import (
			add_log_based_on_employee_field,
		)

		accepted = inspect.signature(add_log_based_on_employee_field).parameters
		self.assertEqual(
			checkin_helper_takes_coordinates(),
			"latitude" in accepted and "longitude" in accepted,
		)

	def test_the_probe_answers_yes_or_no_and_nothing_else(self):
		self.assertIn(checkin_helper_takes_coordinates(), (True, False))


class TestTheActivityLog(FrappeTestCase):
	def test_a_line_is_stored_and_only_notable_ones_come_back(self):
		journal = Journal()
		journal.write("quiet detail")
		journal.write("worth reading", notable=True)
		self.assertEqual(journal.notable, ["worth reading"])
		self.assertTrue(frappe.db.exists("Nexus Attendance Log", {"log_entry": "quiet detail"}))

	def test_a_warning_is_marked_and_notable(self):
		journal = Journal()
		journal.warn("the password is not a number")
		self.assertEqual(len(journal.notable), 1)
		self.assertTrue(journal.notable[0].startswith("[WARNING]"))

	def test_a_problem_is_marked_and_notable(self):
		journal = Journal()
		journal.problem("could not reach the machine")
		self.assertTrue(journal.notable[0].startswith("[PROBLEM]"))

	def test_a_refusal_is_recorded_but_kept_out_of_the_headline(self):
		journal = Journal()
		journal.refusal("101 at noon: employee is not active")
		self.assertEqual(journal.notable, [])
		self.assertTrue(frappe.db.exists("Nexus Attendance Log", {"log_entry": ["like", "[REFUSED]%"]}))

	def test_clearing_empties_the_table_and_counts_what_went(self):
		Journal().write("about to be cleared")
		before = frappe.db.count("Nexus Attendance Log")
		self.assertGreater(before, 0)
		self.assertEqual(purge_journal()["deleted"], before)
		self.assertEqual(frappe.db.count("Nexus Attendance Log"), 0)


class TestWhatTheFormIsTold(FrappeTestCase):
	def tearDown(self):
		frappe.cache.delete_value(STATUS_CACHE_KEY)

	def test_nothing_has_run_yet(self):
		frappe.cache.delete_value(STATUS_CACHE_KEY)
		self.assertEqual(current_status(), {})
		self.assertFalse(a_run_is_under_way())

	def test_a_run_still_reporting_progress_is_left_alone(self):
		frappe.cache.set_value(STATUS_CACHE_KEY, {"state": RUNNING, "updated_ts": time.time(), "percent": 40})
		self.assertEqual(current_status()["state"], RUNNING)
		self.assertTrue(a_run_is_under_way())

	def test_a_run_that_went_quiet_is_called_broken_rather_than_left_spinning(self):
		# A killed worker leaves "running" in the cache for ever, and the form
		# would draw a bar that never moves and refuse to start anything new.
		frappe.cache.set_value(STATUS_CACHE_KEY, {"state": RUNNING, "updated_ts": time.time() - 3600})
		status = current_status()
		self.assertEqual(status["state"], BROKEN)
		self.assertIn("without finishing", status["error"])
		self.assertFalse(a_run_is_under_way())

	def test_the_correction_is_written_back_so_it_is_only_worked_out_once(self):
		frappe.cache.set_value(STATUS_CACHE_KEY, {"state": RUNNING, "updated_ts": time.time() - 3600})
		current_status()
		self.assertEqual(read_status()["state"], BROKEN)

	def test_a_finished_run_keeps_its_result_however_old(self):
		frappe.cache.set_value(STATUS_CACHE_KEY, {"state": "done", "updated_ts": 0, "percent": 100})
		self.assertEqual(current_status()["state"], "done")

	def test_progress_can_be_read_back_after_a_read_that_found_nothing(self):
		# Frappe 15 remembers a miss in frappe.local.cache, and a key written
		# with an expiry never refreshes that copy. Reading this key before the
		# first write would then pin None for the rest of the request: the bar
		# would never move and two runs could overlap unnoticed. read_status()
		# passes expires=True to stay out of that local copy.
		frappe.cache.delete_value(STATUS_CACHE_KEY)
		self.assertEqual(current_status(), {})  # the read that does the damage

		a_run().status.begin()

		self.assertEqual(current_status().get("state"), RUNNING)
		self.assertTrue(a_run_is_under_way())

	def test_the_bar_never_reaches_the_end_while_work_remains(self):
		run = a_run(live=False)
		run.status.begin()
		run._slice_start, run._slice_width = 0, 100
		run._show(1.0, "nearly there")
		self.assertLessEqual(read_status()["percent"], 99)

	def test_each_machine_gets_its_own_stretch_of_the_bar(self):
		run = a_run()
		run.status.begin()
		run._slice_start, run._slice_width = 50, 50  # the second of two machines
		run._show(0.5, "halfway through the second machine")
		self.assertEqual(read_status()["percent"], 75)


class TestLookingUpStaff(FrappeTestCase):
	def test_only_active_people_with_a_device_number_are_collected(self):
		found = a_run()._staff_by_device_id()
		self.assertIsInstance(found, dict)
		for device_number, employee in found.items():
			self.assertEqual(frappe.db.get_value("Employee", employee, "status"), "Active")
			self.assertEqual(device_number, device_number.strip())
