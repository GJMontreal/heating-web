import logging
import os
import sqlite3
import time
from threading import Event, Thread

from redis.exceptions import RedisError

from heating_web.history import DATABASE, History
from heating_web.live_state import age_of, read_zone

log = logging.getLogger(__name__)

HISTORY_ROOT = "/var/lib/heating_history"
DATA_FOLDER = "data"
SAMPLE_INTERVAL = 10
COMMIT_INTERVAL = 60
PRUNE_INTERVAL = 3600
SHADOW_FRESH = 60


def fresh_shadow(shadow):
    if shadow is None:
        return None
    age = age_of(shadow.get("time"))
    return shadow if age is not None and age <= SHADOW_FRESH else None


def sample_values(zone):
    reading = zone.current_temperature
    shadow = fresh_shadow(zone.shadow)
    return {
        "temp": None if reading is None or zone.sensor_stale else reading.value,
        "target": zone.target_temperature,
        "mode": zone.target_state,
        "ctl": zone.control_value,
        "hc": zone.heating_cooling_state,
        "boost": None if zone.boost is None else int(bool(zone.boost)),
        "sh_ctl": None if shadow is None else shadow.get("control_value"),
        "sh_state": None if shadow is None else shadow.get("state"),
    }


class Sampler:
    def __init__(self, redis, zones, root=HISTORY_ROOT, is_mounted=os.path.ismount, clock=time.time,
                 interval=SAMPLE_INTERVAL):
        self.redis = redis
        self.zones = zones
        self.root = root
        self.is_mounted = is_mounted
        self.clock = clock
        self.interval = interval
        self.history = None
        self.last_commit = 0
        self.last_prune = 0
        self.warned = set()
        self.stopping = Event()
        self.thread = None

    def warn_once(self, condition, message, *arguments):
        if condition not in self.warned:
            self.warned.add(condition)
            log.warning(message, *arguments)

    def recovered(self, condition):
        self.warned.discard(condition)

    def open(self):
        folder = os.path.join(self.root, DATA_FOLDER)
        if not os.path.isdir(folder):
            self.warn_once("folder", "history is off: %s does not exist", folder)
            return False
        self.history = History(os.path.join(folder, DATABASE))
        self.last_commit = self.clock()
        self.last_prune = self.clock()
        self.recovered("folder")
        log.info("history is on, writing to %s", folder)
        return True

    def release(self):
        history, self.history = self.history, None
        if history is None:
            return
        try:
            history.close()
        except sqlite3.Error as error:
            log.warning("history closed without a final commit: %s", error)

    def sample(self):
        now = self.clock()
        try:
            rows = [(zone.name, sample_values(read_zone(self.redis, zone))) for zone in self.zones]
        except RedisError as error:
            self.warn_once("redis", "history skipped a sample, redis failed: %s", error)
            return
        self.recovered("redis")
        for name, values in rows:
            self.history.add(now, name, **values)

    def commit_if_due(self):
        now = self.clock()
        if now - self.last_commit < COMMIT_INTERVAL:
            return
        self.history.aggregate(now)
        if now - self.last_prune >= PRUNE_INTERVAL:
            self.history.prune(now)
            self.last_prune = now
        self.history.commit()
        self.last_commit = now

    def cycle(self):
        if not self.is_mounted(self.root):
            self.release()
            self.warn_once("mount", "history is off: %s is not a mount point, nothing is written", self.root)
            return
        self.recovered("mount")
        try:
            if self.history is None and not self.open():
                return
            self.sample()
            self.commit_if_due()
        except sqlite3.Error as error:
            self.warn_once("sqlite", "history write failed, will reopen: %s", error)
            self.release()
        else:
            self.recovered("sqlite")

    def run(self):
        try:
            while True:
                try:
                    self.cycle()
                except Exception:
                    log.exception("history cycle failed")
                if self.stopping.wait(self.interval):
                    break
        finally:
            self.release()

    def start(self):
        self.thread = Thread(target=self.run, name="history-sampler", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
