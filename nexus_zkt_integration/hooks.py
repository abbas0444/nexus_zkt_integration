app_name = "nexus_zkt_integration"
app_title = "Nexus ZKT Integration"
app_publisher = "Abbas Raza"
app_description = "Pull attendance punches from ZKTeco biometric devices straight into Employee Checkin."
app_email = "abbasraza0444@gmail.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["frappe/hrms"]

# Shown as a tile on the /apps screen.
add_to_apps_screen = [
	{
		"name": "nexus_zkt_integration",
		"logo": "/assets/nexus_zkt_integration/images/logo.svg",
		"title": "Nexus ZKT Integration",
		"route": "/app/nexus-zkt",
		"has_permission": "nexus_zkt_integration.api.has_app_permission",
	}
]

# Installation
# ------------------

after_install = "nexus_zkt_integration.install.after_install"

# Uninstallation
# ------------------

before_uninstall = "nexus_zkt_integration.uninstall.before_uninstall"

# Scheduled Tasks
# ------------------

scheduler_events = {
	# Pull attendance from every device in Nexus ZKT Settings and push it to
	# Employee Checkin. The scheduler enqueues this on the "long" queue
	# (background worker, 1500s timeout): a device can hold ~30k records, which
	# does not fit in the default queue's 300s limit. The "Sync Attendance Now"
	# button runs the sync directly instead.
	"hourly_long": [
		"nexus_zkt_integration.nexus_biometric_attendance.script.scheduled_sync",
	],
	# Purge the Nexus Attendance Log table.
	"weekly": [
		"nexus_zkt_integration.nexus_biometric_attendance.script.clear_logs",
	],
}

# Testing
# ------------------

# before_tests = "nexus_zkt_integration.install.before_tests"
