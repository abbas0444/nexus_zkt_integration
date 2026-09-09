"""The arrival/departure rules, with no site and no device in sight.

punch.py imports nothing from Frappe, so these are plain unit tests: if one of
them fails, the fault is in the rule and nowhere else.
"""

import unittest
from datetime import datetime, timedelta

from nexus_zkt_integration.nexus_biometric_attendance.punch import (
	ARRIVAL,
	DEPARTURE,
	NO_OPINION,
	REPEAT,
	UNMARKED,
	DirectionRule,
	Punch,
	Reading,
	Tally,
)

NINE_AM = datetime(2026, 3, 2, 9, 0, 0)


def punch(state=NO_OPINION, at=NINE_AM, user_id="101"):
	return Punch(user_id=user_id, at=at, state=state)


def ago(**delta):
	return Reading(NINE_AM - timedelta(**delta), ARRIVAL)


class TestTheMachineHasAnOpinion(unittest.TestCase):
	def setUp(self):
		self.rule = DirectionRule()

	def test_state_zero_is_an_arrival(self):
		self.assertEqual(self.rule.decide(punch(0), None), ARRIVAL)

	def test_state_four_is_an_overtime_arrival(self):
		self.assertEqual(self.rule.decide(punch(4), None), ARRIVAL)

	def test_state_one_is_a_departure(self):
		self.assertEqual(self.rule.decide(punch(1), None), DEPARTURE)

	def test_state_five_is_an_overtime_departure(self):
		self.assertEqual(self.rule.decide(punch(5), None), DEPARTURE)

	def test_the_machine_is_believed_over_the_previous_punch(self):
		# Two arrivals in a row is odd, but the machine watched it happen.
		self.assertEqual(self.rule.decide(punch(0), ago(hours=1)), ARRIVAL)


class TestTheDeviceIsFixedToOneDirection(unittest.TestCase):
	def test_an_entry_only_machine_overrides_the_state(self):
		self.assertEqual(DirectionRule("IN").decide(punch(1), None), ARRIVAL)

	def test_an_exit_only_machine_overrides_the_state(self):
		self.assertEqual(DirectionRule("OUT").decide(punch(0), None), DEPARTURE)

	def test_none_stores_the_punch_with_no_direction(self):
		self.assertEqual(DirectionRule("None").decide(punch(0), None), UNMARKED)

	def test_a_blank_setting_falls_back_to_following_the_machine(self):
		self.assertEqual(DirectionRule(None).decide(punch(0), None), ARRIVAL)
		self.assertEqual(DirectionRule("").decide(punch(0), None), ARRIVAL)


class TestTakingTurns(unittest.TestCase):
	def setUp(self):
		self.rule = DirectionRule()

	def test_the_first_punch_anyone_makes_is_an_arrival(self):
		self.assertEqual(self.rule.decide(punch(), None), ARRIVAL)

	def test_an_arrival_is_followed_by_a_departure(self):
		self.assertEqual(self.rule.decide(punch(), ago(hours=8)), DEPARTURE)

	def test_a_departure_is_followed_by_an_arrival(self):
		previous = Reading(NINE_AM - timedelta(hours=8), DEPARTURE)
		self.assertEqual(self.rule.decide(punch(), previous), ARRIVAL)

	def test_a_previous_punch_with_no_direction_starts_a_fresh_arrival(self):
		previous = Reading(NINE_AM - timedelta(hours=3), UNMARKED)
		self.assertEqual(self.rule.decide(punch(), previous), ARRIVAL)


class TestTheSameFingerTwice(unittest.TestCase):
	def setUp(self):
		self.rule = DirectionRule()

	def test_a_second_press_within_two_minutes_is_one_event(self):
		self.assertEqual(self.rule.decide(punch(), ago(seconds=90)), REPEAT)

	def test_exactly_two_minutes_still_counts_as_the_same_press(self):
		self.assertEqual(self.rule.decide(punch(), ago(seconds=120)), REPEAT)

	def test_a_second_past_the_window_is_a_real_punch(self):
		self.assertEqual(self.rule.decide(punch(), ago(seconds=121)), DEPARTURE)

	def test_the_window_can_be_widened_for_a_slow_machine(self):
		patient = DirectionRule(repeat_window=timedelta(minutes=5))
		self.assertEqual(patient.decide(punch(), ago(minutes=4)), REPEAT)


class TestAShiftNobodyClosed(unittest.TestCase):
	def setUp(self):
		self.rule = DirectionRule()

	def test_an_arrival_still_inside_the_day_closes_normally(self):
		self.assertEqual(self.rule.decide(punch(), ago(hours=13, minutes=59)), DEPARTURE)

	def test_an_arrival_older_than_fourteen_hours_does_not_swallow_the_morning(self):
		# Somebody went home without punching out. Pairing this morning's punch
		# with yesterday's arrival would record a shift running all night.
		self.assertEqual(self.rule.decide(punch(), ago(hours=15)), ARRIVAL)

	def test_a_night_shift_can_be_given_a_longer_limit(self):
		night = DirectionRule(open_shift_limit=timedelta(hours=20))
		self.assertEqual(night.decide(punch(), ago(hours=15)), DEPARTURE)


class TestReadingADeviceRecord(unittest.TestCase):
	def test_a_pyzk_record_becomes_a_punch(self):
		built = Punch.from_device_record({"user_id": 101, "timestamp": NINE_AM, "punch": 0})
		self.assertEqual(built.user_id, "101")  # the machine may give a number
		self.assertEqual(built.at, NINE_AM)
		self.assertEqual(built.state, 0)

	def test_surrounding_spaces_in_the_user_id_are_trimmed(self):
		built = Punch.from_device_record({"user_id": "  102 ", "timestamp": NINE_AM, "punch": 1})
		self.assertEqual(built.user_id, "102")

	def test_a_record_with_no_state_field_means_no_opinion(self):
		built = Punch.from_device_record({"user_id": "103", "timestamp": NINE_AM})
		self.assertEqual(built.state, NO_OPINION)


class TestCounting(unittest.TestCase):
	def test_it_counts_each_direction_separately(self):
		tally = Tally()
		tally.count(ARRIVAL)
		tally.count(ARRIVAL)
		tally.count(DEPARTURE)
		tally.count(UNMARKED)
		self.assertEqual((tally.arrivals, tally.departures, tally.unmarked), (2, 1, 1))
		self.assertEqual(tally.stored, 4)

	def test_the_summary_says_what_happened(self):
		tally = Tally(arrivals=3, departures=2, already_known=4, repeats=1)
		summary = tally.describe("front-door", 10)
		self.assertIn("front-door", summary)
		self.assertIn("3 arrivals and 2 departures", summary)
		self.assertIn("4 were already recorded", summary)
		self.assertIn("1 repeated presses were ignored", summary)

	def test_the_summary_stays_quiet_about_what_did_not_happen(self):
		summary = Tally(arrivals=1).describe("front-door", 1)
		self.assertNotIn("refused", summary)
		self.assertNotIn("without a direction", summary)

	def test_it_mentions_refusals_when_there_were_some(self):
		self.assertIn("2 were refused by HRMS", Tally(rejected=2).describe("front-door", 2))
