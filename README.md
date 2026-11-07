# heating-web

Web service for the heating system: a read-only API and the web interface it serves. It reads redis. The only key it writes is its own version, `heating/versions/heating-web`.

It is deployed and versioned on its own, apart from the control service in `boiler-relay`. The two share only the redis keys listed in `docs/redis-contract.md` of the parent repo, `GJMontreal/heating-system`. The web service reads the control service's `system_config.json` as plain JSON for each zone's `name`, `sensor_path` and `system`. It imports nothing from `boiler_relay`.

## API

| Route | Returns |
| --- | --- |
| `GET /api/live` | Each zone's `system`, Homebridge keys, the sensor age, a stale flag, and the published `heating/active` and `heating/shadow` state |
| `GET /api/io` | The physical pin levels. `boiler` is `{pin, exported, level, active, on}`. Each hydronic zone lists `outputs` (`pin`, `exported`, `level`, `active`, `since`, `end_switch`) and `end_switches` (`pin`, `exported`, `level`, `high`, `since`). An electric zone has one output, `{type: "mqtt", state: "unconfirmed"}`, and no end switches. `time` is the server clock, so a client measures durations against it. See Pin levels |
| `GET /api/services` | `systemctl is-active` for `boiler_relay`, `boiler_relay_v2`, `boiler_relay_v2_shadow` and `mqtt_bridge` |
| `GET /api/logs?unit=&lines=` | Journal entries for those units. `lines` defaults to 100 and is capped at 500. A failing `journalctl` gives 503 |
| `GET /api/versions` | `service`, `version`, `commit` and `time` for every `heating/versions/*` key, plus this service's own entry. It answers with only its own entry when redis is down |

The API has no write routes.

## Pin levels

`/api/io` reads `/sys/class/gpio/gpio<N>/value` for the boiler pin and for each hydronic zone's valve outputs and end switches. The pins and the `active_low` settings come from the control service's `system_config.json`, read as plain JSON. The pin numbers come from a table of the BeagleBone P8 and P9 header pins in `heating_web/gpio.py`. The pins in use were checked on the device by reading their values.

- **Read only.** The service opens each value file for reading and never exports, unexports or writes. The `heating` user can write those files, so a test checks the code for any write call and checks that the files are unchanged after a read.
- **Polarity.** An output pin with `active_low` is active at level 0 and inactive at level 1. Otherwise it is the opposite. A zone's `active_low` defaults to false and the boiler's to true, as in `boiler-relay`. An end switch at level 1 is high and means the valve is open. The boiler is on when its pin is active.
- **Missing pins.** A pin that is not exported, cannot be read or is not in the table has `level: null` and `exported: false`. That is not an error. A config without outputs or a boiler section gives null for those fields.
- **`since`.** The time this service first saw the pin at its current level, in UTC. It is null until the service has seen the pin change. The service keeps it in memory and updates it on each request, so it resets when the service restarts.

## Web interface

`web/` holds plain HTML, CSS and JavaScript with no build step and no request to anything outside the device. The app serves it at `/`, after the API routes. Every page makes GET requests only and writes API strings with `textContent`.

- **Live** (`#live`): the four unit states, then the zones grouped into a Hydronic and an Electric section. Each zone shows the temperature and its age, the target and target mode, boost, the legacy control value and the shadow decision. A zone with a stale reading reads "No heat: reading is stale". The Hydronic I/O table above the hydronic zone cards has Signal, Pin and State columns for the boiler, each valve output and each end switch. The boiler reads On or Off and an end switch reads Open (high) or Closed (low). Each valve reads Open, Opening, Closing or Closed from its output and end switch, with a warning when Opening or Closing lasts more than 6 minutes. The pin level and the output command are in the tooltip of each State cell. The Stairwell card says its relay state is not confirmed. The page refreshes every 10 seconds and shows a banner when the API cannot be reached.
- **Logs** (`#logs`): `/api/logs` with a unit filter, a level filter, a line count, a refresh button and an auto refresh switch that starts off. The level filter runs in the browser on the lines the API returned. The newest line is first.
- **Footer**: the version and commit of every service from `/api/versions`, refreshed every 60 seconds. The start time is in the tooltip.

Trends and Compare need history and are not built. See `TODO.md`.

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
| `--gpio-root` | `/sys/class/gpio` |
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

`./deploy.sh <user> <host>` fills in the unit and setup templates, syncs the package and `web/` with `rsync --delete` and builds a virtualenv on the device. It installs to `/var/lib/heating_web` and runs as `SERVICE_USER`, default `heating`. The caller creates that user. `.venv` survives the sync. The unit passes `--port 8090`, not the default 8080. On the device these ports are already in use: 6379 (redis), 1883 (MQTT), 8000, 8080 (nginx) and 8581. Pick a free port for anything new. The script refuses `/var/lib/boiler_relay`, `/var/lib/boiler_relay_v2`, `/var/lib/mqtt_bridge` and `/var/lib/mqtt_bridge_v2`.

The virtualenv build and every pip install run under `nice -n 19 ionice -c3`, so they cannot starve the live services on the single core.

The script prints the commands that install `heating_web.service` and restart it. The unit starts after `redis.service` and does not depend on or conflict with any `boiler_relay` unit. Restarting it never touches `boiler_relay_v2`.

`GET /api/logs` needs the service user to be in the `systemd-journal` group. The master deploy script adds it.
