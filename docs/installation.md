# Installation

These steps are for a self-hosted bench. On **Frappe Cloud**, add the app to your
bench and install it on your site from the dashboard instead.

This is the **version-15** branch, for Frappe, ERPNext and HRMS version 15.

## Install

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/abbas0444/nexus_zkt_integration --branch version-15
bench --site your-site install-app nexus_zkt_integration
```

## Update

```bash
cd $PATH_TO_YOUR_BENCH/apps/nexus_zkt_integration && git pull
cd $PATH_TO_YOUR_BENCH
bench --site your-site migrate
bench --site your-site clear-cache
bench restart          # production only
```

## Background workers

Syncs run in the background, so workers must be running: `bench start` in
development, supervisor in production. If pressing **Sync Attendance Now** does
nothing, check that the workers are up and the queue is not paused.

Back to the [README](../README.md).
