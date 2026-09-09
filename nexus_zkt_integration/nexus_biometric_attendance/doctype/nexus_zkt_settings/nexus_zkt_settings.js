// Copyright (c) 2026, Abbas Raza and contributors
// For license information, please see license.txt

const NEXUS_ZKT_EVENT = "nexus_zkt_sync_progress"; // must match AttendanceSyncService.PROGRESS_EVENT
const NEXUS_ZKT_TITLE = __("Reading your devices");
const NEXUS_ZKT_API = "nexus_zkt_integration.nexus_biometric_attendance.script";

frappe.ui.form.on("Nexus ZKT Settings", {
	refresh(frm) {
		nexus_zkt_show_intro(frm);
		nexus_zkt_bind_realtime(frm);
		nexus_zkt_fetch_status(frm); // after a page refresh: re-show a running bar or the last result

		frm.add_custom_button(__("Sync Attendance Now"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save your changes first, then sync."));
				return;
			}
			nexus_zkt_sync_now(frm);
		}).addClass("btn-primary");

		frm.add_custom_button(__("Open Activity Log"), () => {
			frappe.set_route("List", "Nexus Attendance Log");
		});

		frm.add_custom_button(__("Clear Device Memory"), () => nexus_zkt_clear_device(frm));
	},
});

// A brand new install has no devices. Say what to do rather than showing an
// empty grid and a Sync button that would have nothing to read.
function nexus_zkt_show_intro(frm) {
	if ((frm.doc.devices || []).length) {
		frm.set_intro("");
		return;
	}
	frm.set_intro(
		__(
			"Add your first device below - a name you choose and the device's IP address. Then save and press Sync Attendance Now."
		),
		"blue"
	);
}

function nexus_zkt_bind_realtime(frm) {
	if (frm._nexus_zkt_bound) return;
	frm._nexus_zkt_bound = true;
	frappe.realtime.on(NEXUS_ZKT_EVENT, (status) => nexus_zkt_render(frm, status));
}

function nexus_zkt_fetch_status(frm) {
	frappe.call({
		method: `${NEXUS_ZKT_API}.get_sync_status`,
		callback: (r) => nexus_zkt_render(frm, r.message),
	});
}

// Draw the sync state at the top of the form: a progress bar while running,
// the outcome as a headline once finished.
function nexus_zkt_render(frm, status) {
	if (!status || !status.state) return;
	clearTimeout(frm._nexus_zkt_poll);

	if (status.state === "running") {
		frm.dashboard.show_progress(
			NEXUS_ZKT_TITLE,
			status.percent || 1,
			status.description || ""
		);
		frm._nexus_zkt_poll = setTimeout(() => nexus_zkt_fetch_status(frm), 3000); // fallback when realtime is down
		return;
	}

	if (frm.dashboard._progress_map && frm.dashboard._progress_map[NEXUS_ZKT_TITLE]) {
		frm.dashboard.hide_progress(NEXUS_ZKT_TITLE);
	}

	const lines = status.lines || [];
	const failed = status.state === "failed";
	const warn = lines.some((l) => l.includes("[DEVICE ERROR]") || l.includes("WARNING"));
	const title = failed
		? __("Could not finish")
		: warn
		? __("Finished, but some devices had trouble")
		: __("All done");
	const color = failed ? "red" : warn ? "orange" : "green";
	const when = status.finished
		? " &middot; " + __("Finished at {0}, took {1} s", [status.finished, status.took_seconds])
		: "";
	const error = failed && status.error ? `<br>${frappe.utils.escape_html(status.error)}` : "";
	const body = lines.length
		? lines.map((l) => frappe.utils.escape_html(l)).join("<br>")
		: __("Nothing to do.");
	frm.dashboard.set_headline_alert(
		`<b>${title}</b>${when}${error}<br>${body}<br>` +
			`<a href="/app/nexus-attendance-log">${__("Open Activity Log")}</a>`,
		color,
		true
	);
}

function nexus_zkt_sync_now(frm) {
	frm.dashboard.clear_headline();
	frm.dashboard.show_progress(NEXUS_ZKT_TITLE, 1, __("Starting..."));
	// Runs right now, like `bench execute`; the request returns when the sync is done.
	frappe.call({
		method: `${NEXUS_ZKT_API}.sync_attendance_log_to_erpnext`,
		args: { force: 1 },
		callback() {
			frm.reload_doc(); // Last Read changed; refresh() then shows the result headline
		},
		error() {
			nexus_zkt_fetch_status(frm); // e.g. "already running": show that run's bar
		},
	});
}

// Wiping a device is irreversible and the punches live nowhere else until a sync
// has copied them, so the person has to pick the device and type its name back.
function nexus_zkt_clear_device(frm) {
	const names = (frm.doc.devices || []).map((d) => d.device_id).filter(Boolean);
	if (!names.length) {
		frappe.msgprint(__("Add a device first."));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Clear Device Memory"),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p>${__(
					"This erases every punch stored on the device itself. Punches that have not been synced yet cannot be recovered. Run a sync first."
				)}</p>`,
			},
			{
				fieldname: "device_id",
				fieldtype: "Select",
				label: __("Device"),
				options: names.join("\n"),
				default: names[0],
				reqd: 1,
			},
			{
				fieldname: "confirm",
				fieldtype: "Data",
				label: __("Type the device name to confirm"),
				reqd: 1,
			},
		],
		primary_action_label: __("Erase"),
		primary_action(values) {
			if (values.confirm !== values.device_id) {
				frappe.msgprint(__("The name does not match. Nothing was erased."));
				return;
			}
			dialog.hide();
			frappe.call({
				method: `${NEXUS_ZKT_API}.clear_device_logs`,
				args: { device_id: values.device_id },
				freeze: true,
				freeze_message: __("Erasing..."),
				callback(r) {
					const lines = (r.message && r.message.lines) || [];
					frappe.msgprint({
						title: __("Clear Device Memory"),
						message: lines.length
							? lines.map((l) => frappe.utils.escape_html(l)).join("<br>")
							: __("Done."),
						indicator: "orange",
					});
				},
			});
		},
	});
	dialog.show();
	dialog.get_primary_btn().removeClass("btn-primary").addClass("btn-danger");
}
