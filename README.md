# heating-web

Web service for the heating system: a read-only API and the web interface it serves. It reads redis. The only key it writes is its own version, `heating/versions/heating-web`.

It is deployed and versioned on its own, apart from the control service in `boiler-relay`. The two share only the redis keys listed in `docs/redis-contract.md` of the parent repo, `GJMontreal/heating-system`. The web service reads the control service's `system_config.json` as plain JSON for each zone's `name`, `sensor_path` and `system`. It imports nothing from `boiler_relay`.

## API

| Route | Returns |
| --- | --- |
| `GET /api/live` | Each zone's Homebridge keys, the sensor age, a stale flag, and the published `heating/active` and `heating/shadow` state |
| `GET /api/services` | `systemctl is-active` for `boiler_relay`, `boiler_relay_v2`, `boiler_relay_v2_shadow` and `mqtt_bridge` |
| `GET /api/logs?unit=&lines=` | Journal entries for those units. `lines` defaults to 100 and is capped at 500. A failing `journalctl` gives 503 |
| `GET /api/versions` | `service`, `version`, `commit` and `time` for every `heating/versions/*` key, plus this service's own entry. It answers with only its own entry when redis is down |

The API has no authentication and no write routes.

## Running

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m heating_web --zones /path/to/system_config.json
```

| Flag | Default |
| --- | --- |
| `--host` | `127.0.0.1` |
| `--port` | `8080` |
| `--zones` | `/var/lib/boiler_relay_v2/config/system_config.json` |
| `--redis-host` | `localhost` |
| `--redis-port` | `6379` |

`python -m heating_web --version` prints `heating_web <version> (<commit>)`. A missing or unreadable zones file exits 2. If redis is down at startup, the service logs a warning and runs without publishing its version key.

## Testing

```
pip install -r requirements-dev.txt
python -m pytest -q
```

The device runs Python 3.7.3, so the code and the pins in `requirements.txt` stay on 3.7. `requirements-dev.txt` lists its own dependencies because `fakeredis` needs a newer `redis` than the device's pinned `redis==3.5.3`.

## Versions

`heating_web/version.py` holds `__version__`. Releases are `vX.Y.Z` git tags. The commit comes from `build_info.json`, which `deploy.sh` writes. It reads `unknown` when the file is missing.

## Deploying

`./deploy.sh <user> <host>` fills in the unit and setup templates, syncs the package with `rsync --delete` and builds a virtualenv on the device. It installs to `/var/lib/heating_web` and runs as `SERVICE_USER`, default `heating`. The caller creates that user. `.venv` survives the sync. The script refuses `/var/lib/boiler_relay`, `/var/lib/boiler_relay_v2`, `/var/lib/mqtt_bridge` and `/var/lib/mqtt_bridge_v2`.

The script prints the commands that install `heating_web.service` and restart it. The unit starts after `redis.service` and does not depend on or conflict with any `boiler_relay` unit. Restarting it never touches `boiler_relay_v2`.

`GET /api/logs` needs the service user to be in the `systemd-journal` group. The master deploy script adds it.
