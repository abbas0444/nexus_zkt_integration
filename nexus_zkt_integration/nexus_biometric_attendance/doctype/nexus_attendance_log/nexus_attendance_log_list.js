// Copyright (c) 2026, Abbas Raza and contributors
// For license information, please see license.txt

frappe.listview_settings["Nexus Attendance Log"] = {
	onload(listview) {
		const btn = listview.page.add_inner_button(__("Clear Logs"), () => {
			frappe.confirm(__("Delete every entry in this activity log?"), () => {
				frappe.call({
					method: "nexus_zkt_integration.nexus_biometric_attendance.api.purge_journal",
					freeze: true,
					freeze_message: __("Clearing..."),
					callback(r) {
						const n = (r.message && r.message.deleted) || 0;
						frappe.show_alert({
							message: __("{0} entries cleared.", [n]),
							indicator: "green",
						});
						listview.refresh();
					},
				});
			});
		});

		btn.removeClass("btn-default").addClass("btn-danger");
	},
};
