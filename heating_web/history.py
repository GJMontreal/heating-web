import sqlite3

SAMPLE_COLUMNS = ("temp", "target", "mode", "ctl", "hc", "boost", "sh_ctl", "sh_state", "out", "sw", "profile", "live")
RAW_RETENTION = 7 * 24 * 3600
WINDOW_RETENTION = 14 * 24 * 3600
WINDOW_SECONDS = 600
DATABASE = "history.sqlite3"

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS zones (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)",
    "CREATE TABLE IF NOT EXISTS samples (zone INTEGER NOT NULL, ts INTEGER NOT NULL, temp REAL, target REAL,"
    " mode INTEGER, ctl REAL, hc INTEGER, boost INTEGER, sh_ctl REAL, sh_state INTEGER, out REAL, sw REAL,"
    " PRIMARY KEY (zone, ts)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS windows (zone INTEGER NOT NULL, start INTEGER NOT NULL, n INTEGER NOT NULL,"
    " temp REAL, target REAL, ctl REAL, sh_ctl REAL, on_fraction REAL, sh_on_fraction REAL,"
    " out_fraction REAL, sw_fraction REAL, PRIMARY KEY (zone, start)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS boiler (ts INTEGER PRIMARY KEY, state INTEGER)",
    "CREATE TABLE IF NOT EXISTS boiler_windows (start INTEGER PRIMARY KEY, n INTEGER NOT NULL, on_fraction REAL)",
    "CREATE TABLE IF NOT EXISTS profiles (id INTEGER PRIMARY KEY, gains TEXT NOT NULL UNIQUE)",
)

ADDED_COLUMNS = (
    ("samples", "out", "REAL"),
    ("samples", "sw", "REAL"),
    ("windows", "out_fraction", "REAL"),
    ("windows", "sw_fraction", "REAL"),
    ("samples", "profile", "INTEGER"),
    ("windows", "profile", "INTEGER"),
    ("samples", "live", "INTEGER"),
    ("windows", "live", "INTEGER"),
)


def latest_in_window(column):
    return (
        f"(SELECT {column} FROM samples AS latest WHERE latest.zone = samples.zone AND latest.{column} IS NOT NULL"
        " AND latest.ts >= (samples.ts / :width) * :width AND latest.ts < (samples.ts / :width) * :width + :width"
        " ORDER BY latest.ts DESC LIMIT 1)"
    )


AGGREGATE = (
    "INSERT OR REPLACE INTO windows (zone, start, n, temp, target, ctl, sh_ctl, on_fraction, sh_on_fraction,"
    " out_fraction, sw_fraction, profile, live)"
    " SELECT zone, (ts / :width) * :width AS start, count(*), avg(temp), avg(target), avg(ctl), avg(sh_ctl),"
    " avg(hc), avg(sh_state), avg(out), avg(sw), "
    + latest_in_window("profile") + ", " + latest_in_window("live") +
    " FROM samples WHERE ts >= :begin AND ts < :end GROUP BY zone, start"
)
AGGREGATE_BOILER = (
    "INSERT OR REPLACE INTO boiler_windows (start, n, on_fraction)"
    " SELECT (ts / :width) * :width AS start, count(*), avg(state)"
    " FROM boiler WHERE ts >= :begin AND ts < :end GROUP BY start"
)


class History:
    def __init__(self, path):
        self.connection = sqlite3.connect(path, timeout=5)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        for statement in SCHEMA:
            self.connection.execute(statement)
        self.add_missing_columns()
        self.connection.commit()
        self.zone_ids = {}
        self.profile_ids = {}

    def add_missing_columns(self):
        for table, column, kind in ADDED_COLUMNS:
            existing = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

    def zone_id(self, name):
        if name not in self.zone_ids:
            self.connection.execute("INSERT OR IGNORE INTO zones (name) VALUES (?)", (name,))
            row = self.connection.execute("SELECT id FROM zones WHERE name = ?", (name,)).fetchone()
            self.zone_ids[name] = row[0]
        return self.zone_ids[name]

    def profile_id(self, gains):
        if gains not in self.profile_ids:
            self.connection.execute("INSERT OR IGNORE INTO profiles (gains) VALUES (?)", (gains,))
            row = self.connection.execute("SELECT id FROM profiles WHERE gains = ?", (gains,)).fetchone()
            self.profile_ids[gains] = row[0]
        return self.profile_ids[gains]

    def add(self, ts, zone, **values):
        for column in ("profile", "live"):
            if values.get(column) is not None:
                values[column] = self.profile_id(values[column])
        columns = ["zone", "ts"] + [name for name in SAMPLE_COLUMNS if values.get(name) is not None]
        arguments = [self.zone_id(zone), int(ts)] + [values[name] for name in columns[2:]]
        marks = ", ".join("?" for _ in columns)
        self.connection.execute(f"INSERT OR REPLACE INTO samples ({', '.join(columns)}) VALUES ({marks})", arguments)

    def add_boiler(self, ts, state):
        self.connection.execute("INSERT OR REPLACE INTO boiler (ts, state) VALUES (?, ?)", (int(ts), state))

    def commit(self):
        self.connection.commit()

    def aggregate(self, now):
        self.aggregate_table(now, "windows", "samples", AGGREGATE)
        self.aggregate_table(now, "boiler_windows", "boiler", AGGREGATE_BOILER)

    def aggregate_table(self, now, windows, raw, statement):
        last = self.connection.execute(f"SELECT max(start) FROM {windows}").fetchone()[0]
        first = self.connection.execute(f"SELECT min(ts) FROM {raw}").fetchone()[0]
        if first is None:
            return
        begin = (first // WINDOW_SECONDS) * WINDOW_SECONDS if last is None else last + WINDOW_SECONDS
        end = (int(now) // WINDOW_SECONDS) * WINDOW_SECONDS
        if begin < end:
            self.connection.execute(statement, {"width": WINDOW_SECONDS, "begin": begin, "end": end})

    def prune(self, now):
        self.connection.execute("DELETE FROM samples WHERE ts < ?", (int(now) - RAW_RETENTION,))
        self.connection.execute("DELETE FROM boiler WHERE ts < ?", (int(now) - RAW_RETENTION,))
        self.connection.execute("DELETE FROM windows WHERE start < ?", (int(now) - WINDOW_RETENTION,))
        self.connection.execute("DELETE FROM boiler_windows WHERE start < ?", (int(now) - WINDOW_RETENTION,))

    def close(self):
        try:
            self.connection.commit()
        finally:
            self.connection.close()
