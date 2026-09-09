# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt

"""Talking to the machine on the wall.

Everything that speaks the ZK protocol lives here, so the rest of the app deals
in punches rather than sockets.
"""

from contextlib import contextmanager

from zk import ZK

from .punch import Punch

DEFAULT_ZK_PORT = 4370
CONNECT_TIMEOUT = 10


def device_port(device):
	"""Which port to knock on.

	Two machines cannot share an address on a network, but they very often
	share one *public* address: the office router forwards 4370 to the front
	door and some other port to the back. An empty field means the standard one.
	"""
	return int(device.get("port") or DEFAULT_ZK_PORT)


class DeviceUnreachable(Exception):
	"""The machine did not answer. Carries a sentence fit to show someone."""

	def __init__(self, device_name, address, port, cause):
		self.device_name = device_name
		self.address = address
		self.port = port
		self.cause = cause
		super().__init__(f"Could not reach {device_name} at {address}:{port} from this server - {cause}")


def communication_key(device, on_warning=None):
	"""The numeric key pyzk wants, from the Device Password field.

	Almost no machine has one set, so an empty field means zero. A field holding
	letters is a mistake worth saying out loud rather than failing on.
	"""
	stored = device.get_password("device_password", raise_exception=False)
	if not stored:
		return 0
	try:
		return int(stored)
	except (TypeError, ValueError):
		if on_warning:
			on_warning(
				f"{device.device_id}: the Device Password is not a number, so it was ignored. "
				"Clear the field, or put the machine's numeric key in it."
			)
		return 0


@contextmanager
def connected(device, on_warning=None):
	"""Open a session to one machine and always close it.

	pyzk shells out to `ping` before connecting unless told not to, which fails
	wherever ICMP is filtered or the binary is absent - a container, a forwarded
	port - even when 4370 is perfectly reachable. Hence ommit_ping.
	"""
	port = device_port(device)
	machine = ZK(
		device.ip,
		port=port,
		password=communication_key(device, on_warning),
		timeout=CONNECT_TIMEOUT,
		ommit_ping=True,
	)
	session = None
	try:
		try:
			session = machine.connect()
		except Exception as cause:
			raise DeviceUnreachable(device.device_id, device.ip, port, cause) from cause
		yield session
	finally:
		if session:
			# The work is already done or already lost; a machine that drops the
			# socket while we hang up must not turn either outcome into a crash.
			try:
				session.enable_device()
			except Exception:
				pass
			try:
				session.disconnect()
			except Exception:
				pass


def read_punches(device, on_warning=None):
	"""Every punch the machine is holding, oldest first.

	The device is put in a disabled state for the read so nobody can punch
	halfway through and produce a torn log.
	"""
	with connected(device, on_warning) as session:
		try:
			session.disable_device()
		except Exception:
			pass  # older firmware refuses this; the read still works
		records = session.get_attendance() or []

	punches = [Punch.from_device_record(record.__dict__) for record in records]
	punches.sort(key=lambda p: p.at)
	return punches


def erase_punches(device, on_warning=None):
	"""Wipe the machine's own memory. Irreversible, and never automatic."""
	with connected(device, on_warning) as session:
		session.clear_attendance()
