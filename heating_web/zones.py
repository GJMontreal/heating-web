from collections import namedtuple
from json import load

DEFAULT_ZONES = "/var/lib/boiler_relay_v2/config/system_config.json"

Zone = namedtuple("Zone", ["name", "sensor_path", "system"])


class ZonesError(Exception):
    pass


def load_zones(path):
    try:
        with open(path, "r") as file:
            data = load(file)
    except OSError as error:
        raise ZonesError(f"cannot read {path}: {error}")
    except ValueError as error:
        raise ZonesError(f"{path} is not valid JSON: {error}")
    try:
        return [Zone(zone["name"], zone["sensor_path"], zone["system"]) for zone in data["zones"]]
    except (KeyError, TypeError) as error:
        raise ZonesError(f"{path} has no usable zones list: {error!r}")
