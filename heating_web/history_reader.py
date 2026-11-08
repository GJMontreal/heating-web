import json
import math
import os
import sqlite3
import time

from heating_web.history import DATABASE
from heating_web.sampler import DATA_FOLDER, HISTORY_ROOT

TEMPERATURE_DIGITS = 2
FRACTION_DIGITS = 3
MAX_HOURS = 168
MAX_WINDOW_HOURS = 336
RAW_INTERVAL = 10
SERIES_COLUMNS = ("temp", "target", "ctl", "sh_ctl", "hc", "sh_state", "out", "sw")
WINDOW_COLUMNS = ("n", "temp", "target", "ctl", "sh_ctl", "on_fraction", "sh_on_fraction", "out_fraction", "sw_fraction")
SERIES_DIGITS = 2
MAX_MINUTES = MAX_HOURS * 60
MIN_MINUTES = 5
ROUNDING = {"temp": TEMPERATURE_DIGITS, "target": TEMPERATURE_DIGITS}
LEGACY_COLUMNS = ("ctl", "hc")
LEGACY_WINDOW_COLUMNS = ("ctl", "on_fraction")
SUMMARY_COLUMNS = ("ctl", "sh_ctl", "on_fraction", "sh_on_fraction")

SERIES_SQL = (
    "SELECT (ts / :bucket) * :bucket AS t, avg(temp), avg(target), avg(ctl), avg(sh_ctl), avg(hc), avg(sh_state),"
    " avg(out), avg(sw)"
    " FROM samples WHERE zone = :zone AND ts >= :begin AND ts < :end GROUP BY t ORDER BY t"
)
WINDOWS_SQL = (
    "SELECT start, n, temp, target, ctl, sh_ctl, on_fraction, sh_on_fraction, out_fraction, sw_fraction"
    " FROM windows WHERE zone = :zone AND start >= :begin AND start < :end ORDER BY start"
)
PROFILES_SQL = (
    "SELECT windows.start, shadow.gains, live.gains FROM windows"
    " LEFT JOIN profiles AS shadow ON shadow.id = windows.profile"
    " LEFT JOIN profiles AS live ON live.id = windows.live"
    " WHERE windows.zone = :zone AND windows.start >= :begin AND windows.start < :end ORDER BY windows.start"
)
PID_FIELDS = ("kp", "ki", "kd", "integral_cap")
BOILER_SQL = (
    "SELECT (ts / :bucket) * :bucket AS t, avg(state) FROM boiler"
    " WHERE ts >= :begin AND ts < :end GROUP BY t ORDER BY t"
)
BOILER_WINDOWS_SQL = (
    "SELECT start, n, on_fraction FROM boiler_windows WHERE start >= :begin AND start < :end ORDER BY start"
)


class HistoryUnavailable(Exception):
    pass


def rounded(column, value):
    if value is None:
        return None
    return round(value, ROUNDING.get(column, FRACTION_DIGITS))


def compact(value):
    if value is None:
        return None
    digits = round(value, SERIES_DIGITS)
    return int(digits) if digits == int(digits) else digits


def aligned(rows, axis, offset):
    position = {time: index for index, time in enumerate(axis)}
    values = [None] * len(axis)
    for row in rows:
        values[position[row[0]]] = compact(row[offset])
    return values if any(value is not None for value in values) else []


def columns_of(rows, names, offset):
    return {name: [rounded(name, row[offset + index]) for row in rows] for index, name in enumerate(names)}


def any_present(values_by_column, names):
    return any(value is not None for name in names for value in values_by_column[name])


def mean(values):
    present = [value for value in values if value is not None]
    return round(sum(present) / len(present), FRACTION_DIGITS) if present else None


def pid_of(gains):
    return dict(zip(PID_FIELDS, gains)) if len(gains) == len(PID_FIELDS) else None


def changes_of(rows, entry):
    changes = []
    previous = object()
    for start, text in rows:
        if text != previous:
            changes.append({"start": start, **entry(text)})
            previous = text
    return changes


def shadow_entry(text):
    return {"pid": None if text is None else pid_of(json.loads(text))}


def live_entry(text):
    if text is None:
        return {"controller": None, "pid": None}
    marker, *gains = json.loads(text)
    return {"controller": marker, "pid": pid_of(gains)}


class HistoryReader:
    def __init__(self, root=HISTORY_ROOT, is_mounted=os.path.ismount, epoch=time.time):
        self.root = root
        self.is_mounted = is_mounted
        self.epoch = epoch

    def connect(self):
        if not self.is_mounted(self.root):
            raise HistoryUnavailable(f"{self.root} is not a mount point")
        path = os.path.join(self.root, DATA_FOLDER, DATABASE)
        if not os.path.isfile(path):
            raise HistoryUnavailable("the history database does not exist yet")
        try:
            return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error as error:
            raise HistoryUnavailable(str(error))

    def query(self, work):
        connection = self.connect()
        try:
            return work(connection)
        except sqlite3.Error as error:
            raise HistoryUnavailable(str(error))
        finally:
            connection.close()

    def zone_id(self, connection, name):
        row = connection.execute("SELECT id FROM zones WHERE name = ?", (name,)).fetchone()
        return None if row is None else row[0]

    def series(self, zones, seconds, points):
        end = int(self.epoch())
        begin = end - seconds
        bucket = 1 if end - begin <= points * RAW_INTERVAL else math.ceil((end - begin) / points)

        def work(connection):
            fetched = []
            for zone in zones:
                zone_id = self.zone_id(connection, zone.name)
                fetched.append([] if zone_id is None else connection.execute(
                    SERIES_SQL, {"bucket": bucket, "zone": zone_id, "begin": begin, "end": end}).fetchall())
            boiler = connection.execute(BOILER_SQL, {"bucket": bucket, "begin": begin, "end": end}).fetchall()
            axis = sorted({row[0] for rows in fetched for row in rows} | {row[0] for row in boiler})
            result = []
            for zone, rows in zip(zones, fetched):
                values = {name: aligned(rows, axis, 1 + index) for index, name in enumerate(SERIES_COLUMNS)}
                result.append({"name": zone.name, "system": zone.system,
                               "legacy_available": any_present(values, LEGACY_COLUMNS), **values})
            return {"t": axis, "zones": result, "boiler": {"on": aligned(boiler, axis, 1)}}

        return {"start": begin, "end": end, "bucket_seconds": bucket, **self.query(work)}

    def windows(self, zones, hours):
        end = int(self.epoch())
        begin = end - hours * 3600

        def work(connection):
            result = []
            for zone in zones:
                zone_id = self.zone_id(connection, zone.name)
                rows = [] if zone_id is None else connection.execute(
                    WINDOWS_SQL, {"zone": zone_id, "begin": begin, "end": end}).fetchall()
                values = columns_of(rows, WINDOW_COLUMNS, 1)
                profiles = [] if zone_id is None else connection.execute(
                    PROFILES_SQL, {"zone": zone_id, "begin": begin, "end": end}).fetchall()
                result.append({
                    "name": zone.name, "system": zone.system,
                    "legacy_available": any_present(values, LEGACY_WINDOW_COLUMNS),
                    "windows": {"start": [row[0] for row in rows], **values},
                    "profiles": changes_of([(row[0], row[1]) for row in profiles], shadow_entry),
                    "live": changes_of([(row[0], row[2]) for row in profiles], live_entry),
                    "summary": {"windows": len(rows), **{name: mean(values[name]) for name in SUMMARY_COLUMNS}},
                })
            boiler = connection.execute(BOILER_WINDOWS_SQL, {"begin": begin, "end": end}).fetchall()
            return {"zones": result, "boiler": {"start": [row[0] for row in boiler], "n": [row[1] for row in boiler],
                                                "on_fraction": [rounded("on_fraction", row[2]) for row in boiler]}}

        return {"start": begin, "end": end, **self.query(work)}
