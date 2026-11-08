from collections import namedtuple
from json import load

DEFAULT_ZONES = "/var/lib/boiler_relay_v2/config/system_config.json"
ZONE_ACTIVE_LOW = False
BOILER_ACTIVE_LOW = True

Output = namedtuple("Output", ["type", "pin", "end_switch"])
Zone = namedtuple("Zone", ["name", "sensor_path", "system", "outputs", "active_low"], defaults=(None, None))
Boiler = namedtuple("Boiler", ["output_gpio", "active_low"])
Config = namedtuple("Config", ["zones", "boiler", "site_name"], defaults=(None,))


class ZonesError(Exception):
    pass


def read_output(entry):
    return Output(entry.get("type"), entry.get("pin"), entry.get("end_switch"))


def read_outputs(zone):
    entries = zone.get("outputs")
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        return None
    return [read_output(entry) for entry in entries]


def read_zone(zone):
    outputs = read_outputs(zone)
    active_low = None if outputs is None else bool(zone.get("active_low", ZONE_ACTIVE_LOW))
    return Zone(zone["name"], zone["sensor_path"], zone["system"], outputs, active_low)


def read_boiler(data):
    section = data.get("boiler") if isinstance(data, dict) else None
    if not isinstance(section, dict) or "output_gpio" not in section:
        return None
    return Boiler(section["output_gpio"], bool(section.get("active_low", BOILER_ACTIVE_LOW)))


def load_config(path):
    try:
        with open(path, "r") as file:
            data = load(file)
    except OSError as error:
        raise ZonesError(f"cannot read {path}: {error}")
    except ValueError as error:
        raise ZonesError(f"{path} is not valid JSON: {error}")
    try:
        zones = [read_zone(zone) for zone in data["zones"]]
    except (KeyError, TypeError, AttributeError) as error:
        raise ZonesError(f"{path} has no usable zones list: {error!r}")
    return Config(zones, read_boiler(data), data.get("site_name"))
