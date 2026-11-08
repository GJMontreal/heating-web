# heating-web

Web service for the heating system: a read-only API and the web interface it serves. It reads redis. The only key it writes is its own version, `heating/versions/heating-web`. It also writes its history database on the SD card.

It is deployed and versioned on its own, apart from the control service in `boiler-relay`. The two share only the redis keys listed in `docs/redis-contract.md` of the parent repo, `GJMontreal/heating-system`. The web service reads the control service's `system_config.json` as plain JSON for each zone's `name`, `sensor_path` and `system`. It imports nothing from `boiler_relay`.

## API

| Route | Returns |
| --- | --- |
| `GET /api/live` | Each zone's `system`, Homebridge keys, the sensor age, a stale flag, and the published `heating/active` and `heating/shadow` state |
| `GET /api/io` | The physical pin levels. `boiler` is `{pin, exported, level, active, on}`. Each hydronic zone lists `outputs` (`pin`, `exported`, `level`, `active`, `since`, `end_switch`) and `end_switches` (`pin`, `exported`, `level`, `high`, `since`). An electric zone has one output, `{type: "mqtt", state: "unconfirmed"}`, and no end switches. `time` is the server clock, so a client measures durations against it. See Pin levels |
| `GET /api/history?zone=&hours=&minutes=&points=` | Samples for Trends from the history database. `t` is one shared list of epoch seconds for every zone and the boiler. Each zone has columns aligned to `t`: `temp`, `target`, `ctl` (legacy control value), `sh_ctl` (shadow), `hc` (legacy heating state), `sh_state`, `out` (valve output open fraction) and `sw` (end switch open fraction). A column with no value in the range is an empty list. A zone has no row for a time where it has no sample, which reads as null. `boiler` is `{on}`, aligned to `t`. Every number is rounded to 2 decimals and a whole number carries no fraction, so 1 and not 1.0. `hours` is 1 to 168 and defaults to 24. `minutes` is 5 to 10080 and replaces `hours`, and giving both is a 422. Ranges longer than `points` samples at the 10 second interval are averaged into buckets, `bucket_seconds` wide, and a shorter range returns the raw samples with `bucket_seconds` 1. `points` is 10 to 1000 and defaults to 360. Nulls are real gaps. `legacy_available` is false for a zone with no legacy values in the range, such as the electric zone |
| `GET /api/compare?zone=&hours=` | The 10 minute window rows per zone for Compare, legacy and shadow side by side, with a `summary` of the unweighted window means and the same `legacy_available` flag. `profiles` lists the windows where the shadow's PID profile changed, as `{start, pid}` with `pid` null for a window with no profile. The first entry is the first window in the range. `live` lists the changes of the live side the same way, as `{start, controller, pid}` with `controller` `legacy`, `v2` or null and `pid` null when v2 published no gains. The window columns include `out_fraction` and `sw_fraction`, and a `boiler` object has the boiler windows. `hours` is 1 to 336 and defaults to 24 |
| `GET /api/site` | `site_name`, the title of every page. See Site name |
| `GET /api/services` | `systemctl is-active` for `boiler_relay`, `boiler_relay_v2`, `boiler_relay_v2_shadow` and `mqtt_bridge` |
| `GET /api/logs?unit=&lines=` | Journal entries for those units. `lines` defaults to 100 and is capped at 500. A failing `journalctl` gives 503 |
| `GET /api/versions` | `service`, `version`, `commit` and `time` for every `heating/versions/*` key, plus this service's own entry. It answers with only its own entry when redis is down |

The API has no write routes. `/api/compare` rounds temperatures to 2 decimals and control values and fractions to 3. `/api/history` rounds everything to 2. They open the database read-only, because the sampler is its only writer. They answer 503 with a reason when the card is not mounted or the database does not exist yet, and they never create it.

## Redis contract notes

The service reads `pid` (`kp`, `ki`, `kd`, `integral_cap`) in `heating/<mode>/zones/<zone name>`. `heating/active` is the running v2 service and `heating/shadow` is the shadow. `/api/live` passes the keys through unchanged. An electric zone's `heating/active/zones/<zone name>` may also carry `confirmed` (the relay's last reported Power, 0, 1 or null), `confirmed_time` (UTC ISO 8601 with a Z suffix, or null) and `confirmed_silent` (true once a command has gone unconfirmed for 5 seconds). The Live page treats all three as optional and the history does not store them. The sampler stores the shadow's `pid` with each sample. The legacy controller publishes no status keys, so the UI treats legacy as the defaults. The sampler also stores the live controller and gains per zone, taken from the `time` and `pid` of `heating/active/zones/<zone name>`, with no call to systemd.

## Site name

The header and the page title show a site name. The service reads it from the first usable source:

1. The device file `/etc/heating/site.json`, `{"site_name": "Example Site"}`, or the path of `--site-file`. The service reads it again when its modification time changes, so an edit needs no restart. Deploys never touch `/etc`.
2. The top-level `site_name` of the control service's `system_config.json`, if present.
3. `Heating`.

A usable name is a string of 1 to 60 characters after stripping, with no control characters. A bad value falls through to the next source and logs one warning without the value. A missing or unreadable file never fails a request. The page starts with `Heating` and replaces it with the answer of `GET /api/site` through `textContent`, and asks again every 60 seconds. The real name belongs only in the device file and never in a tracked file.

## Pin levels

`/api/io` reads `/sys/class/gpio/gpio<N>/value` for the boiler pin and for each hydronic zone's valve outputs and end switches. The pins and the `active_low` settings come from the control service's `system_config.json`, read as plain JSON. The pin numbers come from a table of the BeagleBone P8 and P9 header pins in `heating_web/gpio.py`. The pins in use were checked on the device by reading their values.

- **Read only.** The service opens each value file for reading and never exports, unexports or writes. The `heating` user can write those files, so a test checks the code for any write call and checks that the files are unchanged after a read.
- **Polarity.** An output pin with `active_low` is active at level 0 and inactive at level 1. Otherwise it is the opposite. A zone's `active_low` defaults to false and the boiler's to true, as in `boiler-relay`. An end switch at level 1 is high and means the valve is open. The boiler is on when its pin is active.
- **Missing pins.** A pin that is not exported, cannot be read or is not in the table has `level: null` and `exported: false`. That is not an error. A config without outputs or a boiler section gives null for those fields.
- **`since`.** The time this service first saw the pin at its current level, in UTC. It is null until the service has seen the pin change. The service keeps it in memory and updates it on each request, so it resets when the service restarts.

## Web interface

`web/` holds plain HTML, CSS and JavaScript with no build step and no request to anything outside the device. The app serves it at `/`, after the API routes. Every page makes GET requests only and writes API strings with `textContent`.

- **Live** (`#live`): the four unit states, then the zones grouped into a Hydronic and an Electric section. Each zone shows the temperature and its age, the target and target mode, boost, the live control value and the shadow decision. The live side reads Legacy while `boiler_relay` is active and Live (v2) while `boiler_relay_v2` is active, from `/api/services`. A zone with a stale reading reads "No heat: reading is stale". The Hydronic I/O card is the first cell of the hydronic zone grid, ahead of the zone cards. Its table has Signal, Pin and State columns for the boiler, each valve output and each end switch. State is a circle only: filled for Open or the boiler On, hollow for Closed or Off, half filled for Opening or Closing, and a warning glyph for an unreadable pin or an Opening or Closing that lasts more than 6 minutes. Each circle carries a visually hidden label with the state word for screen readers. The tooltip of a State cell shows the pin level and its polarity, for example "1, active low", with the duration added on the warning glyph. The Stairwell card says its relay state is not confirmed until the control service publishes the relay's report. With it, an electric zone's Relay row reads commanded state, reported state and the age of the report, with a check mark when they agree, "no report" while `confirmed` is null, an error reading "no report from the relay" while `confirmed_silent` is true, a warning while they differ and an error once they have differed for more than 15 seconds. The 15 seconds run on the server clock between two polls, so the error shows within 10 seconds after that. Hydronic zones and a payload without the fields show nothing new. The page refreshes every 10 seconds and shows a banner when the API cannot be reached.
- **Trends** (`#trends`): a card per zone with a sparkline and the latest temperature, range chips for 30 minutes, 1 hour, 6 hours, 24 hours and 7 days, and a table view. The selected zone shows temperature against target, with the temperature as a smooth curve through the sensor's reports (see Temperature curve), the legacy and shadow control values, and strips for the valve output, the end switch, the boiler, and the legacy and shadow heating state. The output strips are blue and the end switch strip is the lighter ink. A strip with no data is left out. The live side is named as on Live, by the controller live now. The 30 minute and 1 hour ranges draw the raw 10 second samples, with time ticks every 5 and 10 minutes in local time. A run of full samples in a strip is one bar. Gaps in the history are drawn as gaps. A zone with no live values shows only the shadow side.
- **Logs** (`#logs`): `/api/logs` with a unit filter, a level filter, a line count, a refresh button and an auto refresh switch that starts off. The level filter runs in the browser on the lines the API returned. The newest line is first.
- **Compare** (`#compare`): the mean control value or the on-fraction per zone, the live side against shadow, over 24 hours, 7 days or 14 days. A grouped bar chart and a table with the difference and a verdict. A zone diverges when the window means differ by more than 0.05. A zone with no live values reads "No legacy" or "No live (v2)". Two cards follow. PID profiles now gives each zone's live gains next to the shadow's gains, marked Same, Different or Unknown. The live gains come from `pid` in `heating/active/zones/<zone name>` while v2 is live and from the legacy defaults, 1, 0.01, 0.5 and a cap of 1.0, otherwise. The shadow gains come from `pid` in `heating/shadow/zones/<zone name>`. A missing `pid` reads "not published" and breaks nothing. Shadow profile in this range lists the shadow's changes. Live side in this range lists the stored controller and gains per zone and warns when either changed inside the range, because the means then mix windows that ran different gains. The table, chart and verdict name the live side by the stored marker of the range. They fall back to the controller live now when no window has a marker, and read Live when the range holds both controllers.
- **Footer**: the version and commit of every service from `/api/versions`, refreshed every 60 seconds. The start time is in the tooltip.

The charts are plain SVG drawn in the browser.

## History

A sampler thread reads redis every 10 seconds and writes SQLite to `<history root>/data/history.sqlite3`. The history root is the SD card's mount point, `/var/lib/heating_history` by default and `--history-root` otherwise.

- **Mount guard.** Each cycle checks `os.path.ismount` on the history root. If it is not a mount point, the sampler writes nothing, closes the database and logs one warning. If the data folder is missing it also writes nothing and does not create it. The check repeats every cycle, so sampling resumes when the card returns. Nothing is written to the eMMC.
- **Raw samples.** One row per zone every 10 seconds, kept for 7 days: the temperature, target, target mode, the legacy `control_value`, `heating_cooling_state`, boost, the shadow `control_value`, `state` and PID profile, the live controller and its gains, and the physical pins. `out` is the fraction of the zone's valve outputs that are active and `sw` is the fraction of its end switches that are high, read from sysfs through the same read-only path as `/api/io`. Both are null for a zone with no pins and when any of its pins cannot be read. The temperature is null when the reading is stale. The shadow values and the profile are null when the shadow decision is older than 60 seconds, or when its `pid` is missing or not four numbers.
- **Boiler.** One row every 10 seconds in a separate table: 1 when the boiler pin is active, 0 when not, null when it cannot be read.
- **Windows.** One row per zone for each closed 10 minute window, kept for 14 days: the sample count and the means of the temperature, target, legacy and shadow control values, the legacy and shadow on-fractions, the valve output and end switch open fractions, and the shadow profile of the window. A window takes the profile of its latest sample that has one. The live side is stored the same way. A profile is stored once in a `profiles` table and windows and samples hold its id. A shadow profile is the JSON list `[kp, ki, kd, integral_cap]`. A live entry is `[marker, kp, ki, kd, integral_cap]` with the marker `legacy` or `v2`, or `["v2"]` alone when v2 publishes no `pid`. The marker is v2 while `heating/active/zones/<zone name>` is fresh within 60 seconds, null while it has been silent for 60 to 300 seconds, and legacy otherwise, with the legacy defaults as gains. Each window takes the latest non-null marker. The boiler has its own window table. The sampler builds them from the raw samples at each commit.
- **Migration.** Opening a database from 0.4.0 adds the new columns and tables and keeps every row. Old rows and old windows have null pin values. Opening a database from 0.6.0 adds the `profiles` table and the `profile` column of samples and windows. Opening one from 0.7.0 adds the `live` column. Old windows have null profile and live values.
- **SD card wear.** WAL with `synchronous=NORMAL`. Samples are held in one transaction and committed about once a minute, and a stop commits what is pending.
- **Read by.** `GET /api/history` and `GET /api/compare`, which open the database read-only.

## Temperature curve

The sensors report on a long heartbeat or a change threshold, and the sampler stores the last reading every 10 seconds, so the stored temperature is a staircase. Trends draws it as an estimate between the real reports. Nothing changes in the sampler or the API. The target, the control values, the heating states and the strips stay steps, and the table view shows the raw values.

- **Knots.** One per change in the temperature column, at the first sample that shows the new value, plus the first value of each run. A change is 0.005 °C or more. A null sample, or a gap in the samples, ends a run, and the curve never crosses it. In a range averaged into buckets, the bucket that holds a change shows the average of the two readings.
- **Curve.** A monotone cubic, PCHIP, through the knots of a run, in `web/curve.js`. It passes through every knot and never leaves the range of the two knots around it. A local extreme has a flat slope. It does not use sinc interpolation, which rings at steps.
- **Jump limit.** Two knots more than 1 °C apart are not joined, so a stale reading that jumps to a fresh one is not drawn as a ramp. The curve ends at the first knot and starts again at the second.
- **Markers.** A small circle sits on every knot, the real reports.
- **Held value.** From the last knot to the end of the run, or to the right edge of the chart when the run reaches the newest sample, a flat dashed line holds the last value. It is never extrapolated.
- **Fewer than two knots.** The run is a flat solid line with its marker, then the dashed line to the right edge. The 30 minute range often looks like this.
- **Hover.** The tooltip shows the nearest real report and the time it was reported, not an interpolated value. The dot sits on that report.

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
| `--history-root` | `/var/lib/heating_history` |
| `--site-file` | `/etc/heating/site.json` |
| `--redis-host` | `localhost` |
| `--redis-port` | `6379` |

`python -m heating_web --version` prints `heating_web <version> (<commit>)`. A missing or unreadable zones file exits 2. If redis is down at startup, the service logs a warning and runs without publishing its version key.

## Testing

```
pip install -r requirements-dev.txt
python -m pytest -q
```

`tests/js/` holds the JavaScript tests, run with `node --test tests/js/*.test.mjs`. `pytest` runs them too when `node` is installed and skips them otherwise.

The device runs Python 3.7.3, so the code and the pins in `requirements.txt` stay on 3.7. `requirements-dev.txt` lists its own dependencies because `fakeredis` needs a newer `redis` than the device's pinned `redis==3.5.3`.

## Versions

`heating_web/version.py` holds `__version__`. Releases are `vX.Y.Z` git tags. The commit comes from `build_info.json`, which `deploy.sh` writes. It reads `unknown` when the file is missing.

## Deploying

`./deploy.sh <user> <host>` fills in the unit and setup templates, syncs the package and `web/` with `rsync --delete` and builds a virtualenv on the device. It installs to `/var/lib/heating_web` and runs as `SERVICE_USER`, default `heating`. The caller creates that user. `.venv` survives the sync. The unit passes `--port 8090`, not the default 8080. On the device these ports are already in use: 6379 (redis), 1883 (MQTT), 8000, 8080 (nginx) and 8581. Pick a free port for anything new. The script refuses `/var/lib/boiler_relay`, `/var/lib/boiler_relay_v2`, `/var/lib/mqtt_bridge` and `/var/lib/mqtt_bridge_v2`.

The virtualenv build and every pip install run under `nice -n 19 ionice -c3`, so they cannot starve the live services on the single core.

The script prints the commands that install `heating_web.service` and restart it. The unit starts after `redis.service` and does not depend on or conflict with any `boiler_relay` unit. Restarting it never touches `boiler_relay_v2`.

`GET /api/logs` needs the service user to be in the `systemd-journal` group. The master deploy script adds it.
