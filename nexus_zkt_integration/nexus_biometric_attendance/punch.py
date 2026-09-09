# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt

"""Deciding whether a punch is an arrival or a departure.

Nothing here touches Frappe, a database or a device. A punch goes in, a
direction comes out, and the whole thing can be reasoned about — and tested —
on its own.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

# What a ZKTeco machine puts in the "state" field of a punch. Machines with the
# punch-state option switched on report one of these; the rest report NO_OPINION.
ARRIVAL_CODES = frozenset({0, 4})  # check-in, overtime-in
DEPARTURE_CODES = frozenset({1, 5})  # check-out, overtime-out
NO_OPINION = 255

# What decide() can answer.
ARRIVAL = "IN"
DEPARTURE = "OUT"
UNMARKED = ""  # store the punch, leave the direction to the Shift Type
REPEAT = "REPEAT"  # the same finger twice; do not store it at all

# What the Device Name -> "In or Out" setting can say.
FOLLOW_THE_DEVICE = "AUTO"
ALWAYS_ARRIVAL = "IN"
ALWAYS_DEPARTURE = "OUT"
NEVER_MARK = "None"

DEFAULT_REPEAT_WINDOW = timedelta(minutes=2)
DEFAULT_OPEN_SHIFT_LIMIT = timedelta(hours=14)


@dataclass(frozen=True)
class Punch:
	"""One press of a finger, as the machine recorded it."""

	user_id: str
	at: datetime
	state: int = NO_OPINION

	@classmethod
	def from_device_record(cls, record):
		"""Build one from the attribute bag pyzk hands back."""
		return cls(
			user_id=str(record["user_id"]).strip(),
			at=record["timestamp"],
			state=record.get("punch", NO_OPINION),
		)


@dataclass(frozen=True)
class Reading:
	"""The last thing already known about a person: when, and which way."""

	at: datetime
	direction: str


class DirectionRule:
	"""Turns a punch into IN, OUT, nothing, or "ignore this one".

	A machine that reports its own direction is believed. Most are left with
	that option off and report nothing at all, and then the direction has to be
	inferred from the person's previous punch: arrivals and departures take
	turns. Two things stop that inference going wrong.

	A press repeated within `repeat_window` is one event, not two — people press
	twice when the first beep is missed, and storing both would show a shift
	lasting seconds. And an arrival older than `open_shift_limit` was never
	closed: somebody went home without punching out. Pairing the next morning's
	punch with it would record a shift running all night, so the rule treats it
	as a fresh arrival instead.
	"""

	def __init__(
		self,
		mode=FOLLOW_THE_DEVICE,
		repeat_window=DEFAULT_REPEAT_WINDOW,
		open_shift_limit=DEFAULT_OPEN_SHIFT_LIMIT,
	):
		self.mode = mode or FOLLOW_THE_DEVICE
		self.repeat_window = repeat_window
		self.open_shift_limit = open_shift_limit

	def decide(self, punch: Punch, previous: Reading | None) -> str:
		if self.mode == ALWAYS_ARRIVAL:
			return ARRIVAL
		if self.mode == ALWAYS_DEPARTURE:
			return DEPARTURE
		if self.mode == NEVER_MARK:
			return UNMARKED

		if punch.state in ARRIVAL_CODES:
			return ARRIVAL
		if punch.state in DEPARTURE_CODES:
			return DEPARTURE

		return self._infer(punch, previous)

	def _infer(self, punch: Punch, previous: Reading | None) -> str:
		"""The machine said nothing, so take turns from the previous punch."""
		if previous is None:
			return ARRIVAL

		gap = punch.at - previous.at
		if gap <= self.repeat_window:
			return REPEAT
		if previous.direction != ARRIVAL:
			return ARRIVAL
		if gap > self.open_shift_limit:
			return ARRIVAL  # yesterday was never closed; start today cleanly
		return DEPARTURE


@dataclass
class Tally:
	"""How one device's run went, in numbers."""

	arrivals: int = 0
	departures: int = 0
	unmarked: int = 0
	already_known: int = 0
	repeats: int = 0
	rejected: int = 0

	def count(self, direction):
		if direction == ARRIVAL:
			self.arrivals += 1
		elif direction == DEPARTURE:
			self.departures += 1
		else:
			self.unmarked += 1

	@property
	def stored(self):
		return self.arrivals + self.departures + self.unmarked

	def describe(self, device_name, considered):
		parts = [
			f"{device_name}: {considered} punches belonged to active staff",
			f"{self.already_known} were already recorded",
			f"{self.arrivals} arrivals and {self.departures} departures were added",
		]
		if self.unmarked:
			parts.append(f"{self.unmarked} were added without a direction")
		parts.append(f"{self.repeats} repeated presses were ignored")
		if self.rejected:
			parts.append(f"{self.rejected} were refused by HRMS")
		return ", ".join(parts)
