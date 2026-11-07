# TODO

The web service is a read-only API and the web interface it serves. It reads redis and never writes to it. It deploys and versions on its own, apart from `boiler-relay`.

## The move

- [ ] Move `api/` and its tests out of `boiler-relay`, including `GET /api/logs`.
- [ ] Drop the `boiler_relay` imports. Keep a local copy of the redis key names, the time format and the stale limit, so the redis contract is the only thing the two services share.
- [ ] Give the service a version starting at 0.1.0. Serve it at `/api/version`, write `heating/versions/heating-web` at startup, and tag `v0.1.0`.
- [ ] Add `deploy.sh` and a systemd unit of its own, so the web service redeploys and restarts without touching `boiler_relay_v2`.

## API and UI

Moved from `boiler-relay/TODO.md`, step 3.

- [ ] `api/`: a read-only FastAPI service on the LAN with no authentication. Pin FastAPI and pydantic versions that support Python 3.7 and check them when the venv is first built. Pinned in `api/requirements.txt`, and `/api/live`, `/api/services` and `/api/logs` exist. History and the unit are still open.
- [ ] Run it as a new user, `boiler_relay_api`, in the `systemd-journal` group, with its own unit.
- [ ] Sample redis every 10 seconds into SQLite on the USB drive, keep seven days, and include the legacy keys. Mount the drive by UUID as ext4 with `nofail`. Without the drive, run without history and never write to the eMMC.
- [ ] Show `mqtt_bridge.service` state and each sensor's age on the Live page. If the bridge dies, every zone calls for no heat after two hours.
- [ ] Include `mqtt_bridge.service` in the Logs page alongside the control services.
- [ ] `web/`: plain HTML and JavaScript with a small chart library, served by FastAPI. Pages: Live, Trends, Logs (from the journal) and Compare. The footer lists the version of every service from `heating/versions/*`. A static mockup is in `docs/web-mockup/` of the parent repo, `GJMontreal/heating-system`.
