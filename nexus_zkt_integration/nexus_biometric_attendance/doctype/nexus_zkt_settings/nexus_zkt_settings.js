// Copyright (c) 2026, Abbas Raza and contributors
// For license information, please see license.txt

const SERVER = "nexus_zkt_integration.nexus_biometric_attendance.api";
const PROGRESS_EVENT = "nexus_zkt_sync_progress"; // matches journal.PROGRESS_EVENT
const FALLBACK_POLL_MS = 3000; // used only when the socket is down

/**
 * Everything the settings form does beyond editing fields: starting a run,
 * showing how it is going, and erasing a machine on request.
 *
 * One instance per form. It is kept on the form itself so a second refresh
 * reuses it rather than stacking another realtime listener on top.
 */
class SyncPanel {
	constructor(frm) {
		this.frm = frm;
		this.pollTimer = null;
		this.barTitle = __("Reading your devices");
	}

	static attachTo(frm) {
		if (!frm.$nexusPanel) {
			frm.$nexusPanel = new SyncPanel(frm);
			frm.$nexusPanel.listen();
		}
		return frm.$nexusPanel;
	}

	listen() {
		frappe.realtime.on(PROGRESS_EVENT, (status) => this.draw(status));
	}

	/* ---------------------------------------------------------------- */
	/* what the person sees before anything happens                      */
	/* ---------------------------------------------------------------- */
	guide() {
		const hasDevices = (this.frm.doc.devices || []).length > 0;
		this.frm.set_intro(
			hasDevices
				? ""
				: __(
						"Add your first device below - a name you choose and the device's IP address. Then save and press Sync Attendance Now."
				  ),
			"blue"
		);
	}

	addButtons() {
		this.frm
			.add_custom_button(__("Sync Attendance Now"), () => this.start())
			.addClass("btn-primary");
		this.frm.add_custom_button(__("Open Activity Log"), () =>
			frappe.set_route("List", "Nexus Attendance Log")
		);
		this.frm.add_custom_button(__("Clear Device Memory"), () => this.askBeforeErasing());
	}

	/* ---------------------------------------------------------------- */
	/* running                                                           */
	/* ---------------------------------------------------------------- */
	start() {
		if (this.frm.is_dirty()) {
			frappe.msgprint(__("Save your changes first, then sync."));
			return;
		}
		this.frm.dashboard.clear_headline();
		this.frm.dashboard.show_progress(this.barTitle, 1, __("Starting..."));
		frappe.call({
			method: `${SERVER}.collect_now`,
			args: { force: 1 },
			callback: () => this.frm.reload_doc(), // Last Read moved; refresh draws the result
			error: () => this.refreshStatus(), // e.g. already running: show that run
		});
	}

	refreshStatus() {
		frappe.call({
			method: `${SERVER}.sync_status`,
			callback: (r) => this.draw(r.message),
		});
	}

	/* ---------------------------------------------------------------- */
	/* drawing the outcome                                               */
	/* ---------------------------------------------------------------- */
	draw(status) {
		if (!status || !status.state) return;
		clearTimeout(this.pollTimer);

		if (status.state === "running") {
			this.frm.dashboard.show_progress(
				this.barTitle,
				status.percent || 1,
				status.description || ""
			);
			// The socket is the fast path; this is the safety net behind it.
			this.pollTimer = setTimeout(() => this.refreshStatus(), FALLBACK_POLL_MS);
			return;
		}

		this.hideBar();
		this.frm.dashboard.set_headline_alert(this.summarise(status), this.tone(status), true);
	}

	hideBar() {
		const bars = this.frm.dashboard._progress_map;
		if (bars && bars[this.barTitle]) this.frm.dashboard.hide_progress(this.barTitle);
	}

	tone(status) {
		if (status.state === "failed") return "red";
		return this.hasTrouble(status) ? "orange" : "green";
	}

	hasTrouble(status) {
		return (status.lines || []).some((line) => /^\[(PROBLEM|WARNING)\]/.test(line));
	}

	summarise(status) {
		const failed = status.state === "failed";
		const heading = failed
			? __("Could not finish")
			: this.hasTrouble(status)
			? __("Finished, but some devices had trouble")
			: __("All done");

		const timing = status.finished
			? " &middot; " +
			  __("Finished at {0}, took {1} s", [status.finished, status.took_seconds])
			: "";
		const why = failed && status.error ? `<br>${frappe.utils.escape_html(status.error)}` : "";
		const lines = status.lines || [];
		const detail = lines.length
			? lines.map((line) => frappe.utils.escape_html(line)).join("<br>")
			: __("Nothing to do.");

		return (
			`<b>${heading}</b>${timing}${why}<br>${detail}<br>` +
			`<a href="/app/nexus-attendance-log">${__("Open Activity Log")}</a>`
		);
	}

	/* ---------------------------------------------------------------- */
	/* erasing a machine                                                 */
	/* ---------------------------------------------------------------- */
	askBeforeErasing() {
		const names = (this.frm.doc.devices || []).map((row) => row.device_id).filter(Boolean);
		if (!names.length) {
			frappe.msgprint(__("Add a device first."));
			return;
		}

		// Typing the name back is the point: this cannot be undone, and until a
		// sync has copied them the punches exist nowhere but on the machine.
		const ask = new frappe.ui.Dialog({
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
			primary_action: (values) => {
				if (values.confirm !== values.device_id) {
					frappe.msgprint(__("The name does not match. Nothing was erased."));
					return;
				}
				ask.hide();
				this.erase(values.device_id);
			},
		});
		ask.show();
		ask.get_primary_btn().removeClass("btn-primary").addClass("btn-danger");
	}

	erase(deviceId) {
		frappe.call({
			method: `${SERVER}.erase_device`,
			args: { device_id: deviceId },
			freeze: true,
			freeze_message: __("Erasing..."),
			callback: (r) => {
				const lines = (r.message && r.message.lines) || [];
				frappe.msgprint({
					title: __("Clear Device Memory"),
					message: lines.length
						? lines.map((line) => frappe.utils.escape_html(line)).join("<br>")
						: __("Done."),
					indicator: "orange",
				});
			},
		});
	}
}

frappe.ui.form.on("Nexus ZKT Settings", {
	refresh(frm) {
		const panel = SyncPanel.attachTo(frm);
		panel.guide();
		panel.addButtons();
		panel.refreshStatus(); // after a reload: re-show a running bar or the last result
	},
});
