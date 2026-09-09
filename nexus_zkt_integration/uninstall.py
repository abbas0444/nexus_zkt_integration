# Copyright (c) 2026, Abbas Raza and contributors
# For license information, please see license.txt


def before_uninstall():
	"""Drop the cached run status.

	Redis outlives the app: a leftover key would make a later reinstall open on
	the progress bar of a run that happened before it was removed.
	"""
	from nexus_zkt_integration.nexus_biometric_attendance.api import forget_status

	forget_status()
