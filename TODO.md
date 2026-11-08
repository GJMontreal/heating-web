# TODO

The web service is a read-only API and the web interface it serves. It reads redis and writes only its own version key and its history database. It deploys and versions on its own, apart from `boiler-relay`.

## The move

- [x] Move `api/` and its tests out of `boiler-relay`, including `GET /api/logs`.
- [x] Drop the `boiler_relay` imports. Keep a local copy of the redis key names, the time format and the stale limit, so the redis contract is the only thing the two services share.
- [x] Give the service a version starting at 0.1.0. Serve every service's version at `/api/versions`, write `heating/versions/heating-web` at startup, and tag `v0.1.0`.
- [x] Add `deploy.sh` and a systemd unit of its own, so the web service redeploys and restarts without touching `boiler_relay_v2`.

## API and UI

Moved from `boiler-relay/TODO.md`, step 3.

- [x] A read-only FastAPI service on the LAN. The versions in `requirements.txt` are pinned for Python 3.7, and the tests pass on 3.7.17. `/api/live`, `/api/services`, `/api/logs` and `/api/versions` exist. Nothing reads the history yet.
- [x] Run it from its own unit as `SERVICE_USER` (`heating`), not a new user. The master deploy script adds that user to `systemd-journal`.
- [x] Sample redis every 10 seconds into SQLite on the SD card, mounted at `/var/lib/heating_history`. Raw samples for 7 days and 10 minute windows for 14 days, with the legacy keys and the shadow keys. The sampler writes only while the path is a mount point, so it never writes to the eMMC.
- [ ] Deploy the sampler and check on the device that the card is mounted, the database grows and the service user can write the data folder.
- [x] Show the shadow's PID profile on Compare, store it per ten minute window and name the live side Legacy or Live (v2) from `/api/services`. The `pid` field of `heating/<mode>/zones/<zone name>` is the contract field.
- [x] Store the live controller and its gains per zone with each window, read from `heating/active/zones/<zone name>`, and show the changes on Compare. Name the live side on Trends as on Compare and Live.
- [ ] Show the means per segment between live changes, so a range that holds a change needs no manual choice of a later range.
- [ ] Sample the `heating/active` zone keys too, so the Compare page can show the v2 service next to legacy once it runs.
- [x] Show `mqtt_bridge.service` state and each sensor's age on the Live page. If the bridge dies, every zone calls for no heat after two hours.
- [x] Include `mqtt_bridge.service` in the Logs page alongside the control services.
- [x] Physical pin levels: `/api/io` and the Hydronic I/O table on the Live page, from read-only sysfs reads.
- [x] `web/` first slice: Live, Logs and the versions footer, plain HTML, CSS and JavaScript served by FastAPI. A static mockup is in `docs/web-mockup/` of the parent repo, `GJMontreal/heating-system`.
- [x] `web/` Trends and Compare, from `/api/history` and `/api/compare`, drawn as plain SVG.
- [ ] Check the on-fraction against real heat. Every sample so far has the output off, so the on-fraction of a real window has only been tested with built rows. Boost one zone for about 12 minutes and compare the Compare page with the Live page.
- [x] Sample the valve and end switch pin levels and the boiler pin, so Trends shows the output and input strips from the mockup.
- [ ] Check the pin strips on the device after the sampler restarts: the migration keeps the old rows and the new columns fill from the first cycle.
- [ ] Compress the larger API responses if the BeagleBone's link needs it. A 14 day Compare answer is about 115 kB.
- [ ] Live page fields the mockup shows and the API cannot supply yet. Each needs new API fields from the control service's published state:
  - valve open minutes in the duty window
  - sensor battery and humidity
  - the electric relay's last command
