# TODO

The web service is a read-only API and the web interface it serves. It reads redis and writes only its own version key. It deploys and versions on its own, apart from `boiler-relay`.

## The move

- [x] Move `api/` and its tests out of `boiler-relay`, including `GET /api/logs`.
- [x] Drop the `boiler_relay` imports. Keep a local copy of the redis key names, the time format and the stale limit, so the redis contract is the only thing the two services share.
- [x] Give the service a version starting at 0.1.0. Serve every service's version at `/api/versions`, write `heating/versions/heating-web` at startup, and tag `v0.1.0`.
- [x] Add `deploy.sh` and a systemd unit of its own, so the web service redeploys and restarts without touching `boiler_relay_v2`.

## API and UI

Moved from `boiler-relay/TODO.md`, step 3.

- [x] A read-only FastAPI service on the LAN. The versions in `requirements.txt` are pinned for Python 3.7, and the tests pass on 3.7.17. `/api/live`, `/api/services`, `/api/logs` and `/api/versions` exist. History is still open.
- [x] Run it from its own unit as `SERVICE_USER` (`heating`), not a new user. The master deploy script adds that user to `systemd-journal`.
- [ ] Sample redis every 10 seconds into SQLite on the USB drive, keep seven days, and include the legacy keys. Mount the drive by UUID as ext4 with `nofail`. Without the drive, run without history and never write to the eMMC.
- [x] Show `mqtt_bridge.service` state and each sensor's age on the Live page. If the bridge dies, every zone calls for no heat after two hours.
- [x] Include `mqtt_bridge.service` in the Logs page alongside the control services.
- [x] Physical pin levels: `/api/io` and the Hydronic I/O table on the Live page, from read-only sysfs reads.
- [x] `web/` first slice: Live, Logs and the versions footer, plain HTML, CSS and JavaScript served by FastAPI. A static mockup is in `docs/web-mockup/` of the parent repo, `GJMontreal/heating-system`.
- [ ] `web/` Trends and Compare. They need history, which is undecided because the device has no SD card or USB drive. They also need a chart approach that makes no request outside the device.
- [ ] Live page fields the mockup shows and the API cannot supply yet. Each needs new API fields from the control service's published state:
  - valve open minutes in the duty window
  - sensor battery and humidity
  - the electric relay's last command
