import sqlite3

SAMPLE_COLUMNS = ("temp", "target", "mode", "ctl", "hc", "boost", "sh_ctl", "sh_state")
RAW_RETENTION = 7 * 24 * 3600
WINDOW_RETENTION = 14 * 24 * 3600
WINDOW_SECONDS = 600
DATABASE = "history.sqlite3"

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS zones (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)",
    "CREATE TABLE IF NOT EXISTS samples (zone INTEGER NOT NULL, ts INTEGER NOT NULL, temp REAL, target REAL,"
    " mode INTEGER, ctl REAL, hc INTEGER, boost INTEGER, sh_ctl REAL, sh_state INTEGER,"
    " PRIMARY KEY (zone, ts)) WITHOUT ROWID",
    "CREATE TABLE IF NOT EXISTS windows (zone INTEGER NOT NULL, start INTEGER NOT NULL, n INTEGER NOT NULL,"
    " temp REAL, target REAL, ctl REAL, sh_ctl REAL, on_fraction REAL, sh_on_fraction REAL,"
    " PRIMARY KEY (zone, start)) WITHOUT ROWID",
)

AGGREGATE = (
    "INSERT OR REPLACE INTO windows"
    " SELECT zone, (ts / :width) * :width AS start, count(*), avg(temp), avg(target), avg(ctl), avg(sh_ctl),"
    " avg(hc), avg(sh_state)"
    " FROM samples WHERE ts >= :begin AND ts < :end GROUP BY zone, start"
)


class History:
    def __init__(self, path):
        self.connection = sqlite3.connect(path, timeout=5)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        for statement in SCHEMA:
            self.connection.execute(statement)
        self.connection.commit()
        self.zone_ids = {}

    def zone_id(self, name):
        if name not in self.zone_ids:
            self.connection.execute("INSERT OR IGNORE INTO zones (name) VALUES (?)", (name,))
            row = self.connection.execute("SELECT id FROM zones WHERE name = ?", (name,)).fetchone()
            self.zone_ids[name] = row[0]
        return self.zone_ids[name]

    def add(self, ts, zone, **values):
        columns = ["zone", "ts"] + [name for name in SAMPLE_COLUMNS if values.get(name) is not None]
        arguments = [self.zone_id(zone), int(ts)] + [values[name] for name in columns[2:]]
        marks = ", ".join("?" for _ in columns)
        self.connection.execute(f"INSERT OR REPLACE INTO samples ({', '.join(columns)}) VALUES ({marks})", arguments)

    def commit(self):
        self.connection.commit()

    def aggregate(self, now):
        last = self.connection.execute("SELECT max(start) FROM windows").fetchone()[0]
        first = self.connection.execute("SELECT min(ts) FROM samples").fetchone()[0]
        if first is None:
            return
        begin = (first // WINDOW_SECONDS) * WINDOW_SECONDS if last is None else last + WINDOW_SECONDS
        end = (int(now) // WINDOW_SECONDS) * WINDOW_SECONDS
        if begin < end:
            self.connection.execute(AGGREGATE, {"width": WINDOW_SECONDS, "begin": begin, "end": end})

    def prune(self, now):
        self.connection.execute("DELETE FROM samples WHERE ts < ?", (int(now) - RAW_RETENTION,))
        self.connection.execute("DELETE FROM windows WHERE start < ?", (int(now) - WINDOW_RETENTION,))

    def close(self):
        try:
            self.connection.commit()
        finally:
            self.connection.close()
