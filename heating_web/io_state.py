from datetime import datetime, timezone
from threading import Lock

from heating_web.contract import TIME_FORMAT

GPIO = "gpio"


def utc_now():
    return datetime.now(timezone.utc).strftime(TIME_FORMAT)


def is_active(level, active_low):
    if level is None:
        return None
    return level == (0 if active_low else 1)


class Tracker:
    def __init__(self, clock=utc_now):
        self.clock = clock
        self.seen = {}
        self.lock = Lock()

    def since(self, pin, level):
        with self.lock:
            previous = self.seen.get(pin)
            if previous is None:
                self.seen[pin] = (level, None)
                return None
            seen_level, since = previous
            if seen_level == level:
                return since
            since = self.clock()
            self.seen[pin] = (level, since)
            return since


class IoView:
    def __init__(self, zones, boiler, reader, clock=utc_now):
        self.zones = zones
        self.boiler = boiler
        self.reader = reader
        self.clock = clock
        self.tracker = Tracker(clock)

    def snapshot(self):
        return {
            "time": self.clock(),
            "boiler": None if self.boiler is None else self.read_boiler(),
            "zones": [self.read_zone(zone) for zone in self.zones],
        }

    def read_boiler(self):
        level = self.reader.level(self.boiler.output_gpio)
        active = is_active(level, self.boiler.active_low)
        return {"pin": self.boiler.output_gpio, "exported": level is not None, "level": level,
                "active": active, "on": active}

    def read_zone(self, zone):
        if zone.outputs is None:
            return {"name": zone.name, "system": zone.system, "outputs": None, "end_switches": None}
        outputs = []
        end_switches = []
        for output in zone.outputs:
            if output.type != GPIO:
                outputs.append({"type": "mqtt", "state": "unconfirmed"})
            elif output.pin is not None:
                outputs.append(self.read_output(output, zone.active_low))
                if output.end_switch is not None:
                    end_switches.append(self.read_end_switch(output.end_switch))
        return {"name": zone.name, "system": zone.system, "outputs": outputs, "end_switches": end_switches}

    def read_output(self, output, active_low):
        level = self.reader.level(output.pin)
        return {"pin": output.pin, "exported": level is not None, "level": level,
                "active": is_active(level, active_low), "since": self.tracker.since(output.pin, level),
                "end_switch": output.end_switch}

    def read_end_switch(self, pin):
        level = self.reader.level(pin)
        return {"pin": pin, "exported": level is not None, "level": level,
                "high": None if level is None else level == 1, "since": self.tracker.since(pin, level)}
