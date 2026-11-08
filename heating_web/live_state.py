from calendar import timegm
from datetime import datetime, timezone
from json import loads
from typing import Optional

from pydantic import BaseModel

from heating_web.contract import ACTIVE, CONTROL_VALUE, SHADOW, STALE_AFTER, TIME_FORMAT


class Reading(BaseModel):
    value: float
    time: str
    age_seconds: Optional[float]


class ZoneLive(BaseModel):
    name: str
    system: str
    sensor_path: str
    current_temperature: Optional[Reading]
    sensor_stale: bool
    target_temperature: Optional[float]
    target_state: Optional[int]
    control_value: Optional[float]
    heating_cooling_state: Optional[int]
    boost: Optional[bool]
    active: Optional[dict]
    shadow: Optional[dict]


def age_of(sample_time):
    try:
        reported = datetime.strptime(sample_time, TIME_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return max(0.0, (datetime.now(timezone.utc) - reported).total_seconds())


def epoch_of(sample_time):
    try:
        return timegm(datetime.strptime(sample_time, TIME_FORMAT).timetuple())
    except (TypeError, ValueError):
        return None


def read_json(redis, key):
    message = redis.get(key)
    return None if message is None else loads(message)


def read_int(redis, key):
    message = redis.get(key)
    try:
        return None if message is None else int(message)
    except ValueError:
        return None


def read_reading(redis, path):
    data = read_json(redis, f"{path}/current_temperature")
    if data is None:
        return None
    return Reading(value=data["value"], time=data["time"], age_seconds=age_of(data["time"]))


def read_zone(redis, zone):
    path = zone.sensor_path
    reading = read_reading(redis, path)
    target = read_json(redis, f"{path}/target_temperature")
    control = redis.get(f"{path}/{CONTROL_VALUE}")
    return ZoneLive(
        name=zone.name,
        system=zone.system,
        sensor_path=path,
        current_temperature=reading,
        sensor_stale=reading is None or reading.age_seconds is None or reading.age_seconds > STALE_AFTER,
        target_temperature=None if target is None else target["value"],
        target_state=read_int(redis, f"{path}/target_heatingcooling_state"),
        control_value=None if control is None else float(control),
        heating_cooling_state=read_int(redis, f"{path}/heating_cooling_state"),
        boost=read_json(redis, f"{path}/boost"),
        active=read_json(redis, f"heating/{ACTIVE}/zones/{zone.name}"),
        shadow=read_json(redis, f"heating/{SHADOW}/zones/{zone.name}"),
    )
