<div align="center">
  <img src="nexus_zkt_integration/public/images/logo.svg" width="88" alt="Nexus">

  <h1>Nexus ZKT Integration</h1>

  <p><b>Your ZKTeco fingerprint machine, wired straight into ERPNext attendance.</b></p>

  <p>
    Punches go in one end, <b>Employee Checkin</b> records come out the other.
    No exports, no spreadsheets, no typing.
  </p>
</div>

---

## You are on the **version-16** branch

| Your ERPNext / HRMS | Branch to install |
|---|---|
| **Version 16** | `version-16` &nbsp;&larr; *you are here* |
| **Version 15** | [`version-15`](../../tree/version-15) |

Both branches carry the same features. Pick the one that matches the software you
already run, and install it with `--branch`.

---

## What it does

Every run, for each device you have listed:

1. **Look up your people.** Collect the *Attendance Device ID* of every **Active**
   employee.
2. **Read the device.** Pull its attendance log and keep only those people's
   punches. Punches belonging to unknown or inactive users are ignored — nothing
   is stored for them.
3. **Write the check-ins.** Create one **Employee Checkin** per new punch, marked
   **IN** or **OUT**. A punch that is already recorded is skipped, so running the
   sync twice never doubles anything.

Every step is written to the **Nexus Attendance Log**, so you can always see what
happened and why.

## What you need

- Frappe, ERPNext and HRMS **version 16** (use the `version-15` branch for 15)
- The Python package `pyzk` — installed for you with the app
- The device reachable from your server on TCP port **4370**
- Background workers running (`bench start` in development, supervisor in production)

Tested against ZKTeco F22 and K40; anything speaking the ZK SDK protocol on port
4370 should behave the same.

## Install

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/abbas0444/nexus_zkt_integration --branch version-16
bench --site your-site install-app nexus_zkt_integration
```

On **Frappe Cloud**, add the app to your bench and install it on your site from
the dashboard — no commands needed.

### Update

```bash
cd $PATH_TO_YOUR_BENCH/apps/nexus_zkt_integration && git pull
cd $PATH_TO_YOUR_BENCH
bench --site your-site migrate
bench --site your-site clear-cache
bench restart          # production only
```

## Set it up

Everything lives in one place: the **Nexus ZKT** workspace, or the app tile on
your `/apps` screen.

### 1. Add your device

Open **Nexus ZKT Settings** and add one row per machine.

| Field | What to put in it |
|---|---|
| **Device Name** | Any name you like, e.g. `main-entrance`. It is saved on every check-in this device creates. |
| **Device IP Address** | The device's address on your network, e.g. `192.168.1.201`. Port 4370 is assumed. |
| **Device Password** | Only if your device has a numeric communication key. Most do not — leave it empty. |
| **In or Out** | `AUTO` suits almost everyone. Use `IN` or `OUT` for a machine that only records one direction, or `None` to leave it blank. See [How IN and OUT are decided](#how-in-and-out-are-decided). |
| **Check Every (Minutes)** | How long to wait before reading this device again on the hourly schedule. |
| **Last Read** | Filled in for you. Clear it to force the next scheduled run. |
| **Latitude / Longitude** | Optional. Copied onto each check-in. |

Then save.

### 2. Tell ERPNext who is who

On every **Employee**, fill in **Attendance Device ID** with that person's user ID
on the machine — the number the device shows as "User ID", not their name. Only
**Active** employees are read.

To list the users a device holds, run this from your bench folder (change the IP):

```bash
env/bin/python -c "
from zk import ZK
c = ZK('192.168.1.201', port=4370, password=0).connect()
for u in c.get_users(): print(u.user_id, '-', u.name)
c.disconnect()"
```

### 3. Set your Shift Type

In each **Shift Type**, set *Determine Check-in and Check-out* to
**Alternating entries as IN and OUT during the same shift**. This works whether or
not your device records a punch direction, and it is what the IN/OUT logic below
assumes.

## Running a sync

**The button.** Open **Nexus ZKT Settings** and press **Sync Attendance Now**. It
reads every device immediately, ignores the wait time, and shows a progress bar
while it works. If a sync is already going, it tells you instead of starting a
second one.

**Automatically.** The sync runs every hour and respects each device's
*Check Every (Minutes)*. Make sure the scheduler is on:

```bash
bench --site your-site scheduler enable
```

and that `pause_scheduler` is not `1` in `sites/common_site_config.json`.

**From the command line.**

```bash
bench --site your-site execute nexus_zkt_integration.nexus_biometric_attendance.api.collect_now
# ignore the wait time:
bench --site your-site execute nexus_zkt_integration.nexus_biometric_attendance.api.collect_now --kwargs "{'force': 1}"
```

## How IN and OUT are decided

Your device records a *punch direction* with every punch when its **Punch State**
option is switched on (on an F22: Menu → System → Attendance → Punch State Options
→ Manual or Auto). Directions `0` and `4` become **IN**, `1` and `5` become **OUT**.

Most machines are left with Punch State **off** and send `255` — no direction at
all. With **In or Out** set to `AUTO`, the direction is then worked out per person:

- the first punch is **IN**, the next **OUT**, the next **IN**, and so on;
- an **IN** more than **14 hours** old is treated as a day somebody forgot to close,
  so the next punch starts a fresh **IN** rather than closing yesterday;
- a second punch within **2 minutes** of the last one is the same finger twice and
  is ignored.

Both limits are `DEFAULT_OPEN_SHIFT_LIMIT` and `DEFAULT_REPEAT_WINDOW` at the top of
[`punch.py`](nexus_zkt_integration/nexus_biometric_attendance/punch.py).

Check-ins that already exist are never modified. If you want IN/OUT on check-ins
created before you installed this, delete them and sync again — the punches are
still on the device.

## Clearing a device

A sync **never** erases the device's memory. Punches that have not reached ERPNext
yet exist nowhere else, and a wipe cannot be undone.

When a device does fill up, use **Clear Device Memory** on the settings form. It
asks you to pick the device and type its name back before it erases anything. Run
a sync first.

## The activity log

Every run writes to **Nexus Attendance Log**. The list has a **Clear Logs** button,
and the table empties itself once a week.

## When something is wrong

| What the log says | What it means |
|---|---|
| `No Active Employee has an Attendance Device ID; skipping device …` | Nobody has the Attendance Device ID field filled in, or they are not Active. See [step 2](#2-tell-erpnext-who-is-who). |
| `… ignored (no Active Employee with that ID)` | Punches from device users who have no Active employee. Map them to bring their punches in. |
| `Skipping device …; pull frequency not met` | The scheduled run came too early. Use the button, pass `force`, or clear *Last Read*. |
| `[DEVICE ERROR] …` | The device could not be reached. Check the IP, that port 4370 is open, and that no other program is holding the connection. |
| `[DEVICE WARNING] … device password must be numeric, using 0` | The Device Password field holds text. Clear it, or enter the numeric key. |
| `[ERP ERROR] … Transactions cannot be created for an Inactive Employee` | HRMS refused the punch because that employee is not Active. |
| Nothing happens after pressing the button | Background workers are not running (`bench worker` / supervisor), or the queue is paused. |

## Server and device on different networks

The connection goes **from your server to the device** on TCP port 4370. A server
on the internet cannot reach a device sitting on an office LAN address like
`192.168.x.x`; the log then shows `[DEVICE ERROR] … timed out`. Pick one:

**A. Port forwarding.** On the office router, forward TCP port 4370 to the device,
then use the office's public IP as the Device IP Address. ZK devices have almost no
authentication, so restrict the forward to your server's IP if the router allows it.

**B. SSH reverse tunnel**, from any office PC that can reach both:

```bash
ssh -N -R 4370:<device-lan-ip>:4370 <user>@<your-server>
```

While that runs, set Device IP Address to `127.0.0.1`. For a permanent tunnel, run
it through `autossh` or a systemd service.

**C. VPN** (WireGuard, OpenVPN) between server and office. The most secure option;
the device keeps its LAN address.

## Good to know

- Device memory is limited — an F22 holds about 30,000 punches. Sync regularly, and
  clear the device once its punches are safely in ERPNext.
- This app can run alongside ZKTeco BioTime or ADMS push mode. Both read the same
  log; this one connects directly on port 4370.
- The device's own clock is used as-is. Keep it matching your server's timezone.
- Every DocType here is prefixed `Nexus`, so this app can sit on the same site as
  another ZK integration without the two fighting over the same tables.

## Licence

MIT - see [license.txt](license.txt).
