# Changelog

All notable changes to Nexus ZKT Integration. Dates are the day the release was
tagged. Versions follow [semantic versioning](https://semver.org).

## 1.0.0 — 2026-09-10

First public release, for **Frappe / ERPNext / HRMS 15 and 16**.

### What it does

- Reads ZKTeco attendance machines over the ZK protocol and creates one
  **Employee Checkin** per new punch, marked IN or OUT.
- Runs hourly on the scheduler, respecting a per-device interval, or immediately
  from the **Sync Attendance Now** button with a live progress bar.
- Writes every step to the **Nexus Attendance Log**, with a weekly tidy-up.
- Sets each mapped **Shift Type**'s *Last Sync of Checkin*, so HRMS auto
  attendance knows how far the check-ins are complete.
- Ships a **Nexus ZKT** workspace and an entry on the `/apps` screen.

### Multiple doors

- Every machine is read **before** any direction is decided, and all punches are
  merged into one list in time order. A person who walks in the front and out the
  back has one day, not two half-days, and the order devices are listed in makes
  no difference to the result.
- Each machine keeps its own **In or Out** setting, so an entry-only reader and an
  exit-only reader work side by side.
- The two-minute repeat rule spans doors: walking past two readers in one lobby is
  one arrival, not an arrival and a departure a minute apart.
- Devices carry a **Port**, so two machines behind one public address — a router
  forwarding 4370 to one and 4371 to the other — can both be reached.
- Two rows with the same address *and* port are refused on save: that is one
  machine listed twice.

### Deliberately careful

- A sync **never** erases a machine's memory. Clearing is a separate button that
  makes you pick the device and type its name back.
- No example device is created on install, so a fresh site does not log a failure
  every hour against an address nobody owns.
- Duplicate device names are refused: two rows sharing a name would overwrite each
  other's *Last Read* and one device would quietly stop being read.
- A device that could not be reached does not get its *Last Read* stamped, so the
  next scheduled run tries again instead of waiting out the interval.
- The HRMS check-in helper is called through a signature probe, so releases that
  predate its latitude and longitude parameters still work.

### Under the hood

- Five focused modules — `punch`, `reader`, `journal`, `collector`, `api` — with
  the arrival/departure rules in `punch.py`, which imports nothing from Frappe.
- **106 tests**, run on Frappe 15 and 16 on every push. Twenty-seven need no site
  at all.
- Every DocType is prefixed `Nexus`, so this app can share a site with another ZK
  integration without the two colliding.
