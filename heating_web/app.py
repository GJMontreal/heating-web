import subprocess
from datetime import datetime, timezone
from json import loads
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from redis.exceptions import RedisError

from heating_web.contract import (ACTIVE, CONTROL_VALUE, SERVICE_NAME, SHADOW, STALE_AFTER, TIME_FORMAT,
                                  VERSIONS_PREFIX)
from heating_web.journal import JournalError, read_journal

SERVICES = ("boiler_relay", "boiler_relay_v2", "boiler_relay_v2_shadow", "mqtt_bridge")
SYSTEMCTL_TIMEOUT = 5
MAX_LOG_LINES = 500
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


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


class LogEntry(BaseModel):
    time: str
    unit: Optional[str]
    priority: Optional[int]
    message: str


class VersionEntry(BaseModel):
    service: str
    version: str
    commit: str
    time: str


class ServiceState(BaseModel):
    name: str
    state: str


def unit_state(name):
    try:
        result = subprocess.run(["systemctl", "is-active", f"{name}.service"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                universal_newlines=True, timeout=SYSTEMCTL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() or "unknown"


def age_of(sample_time):
    try:
        reported = datetime.strptime(sample_time, TIME_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return max(0.0, (datetime.now(timezone.utc) - reported).total_seconds())


def create_app(zones, redis, own_version, unit_state=unit_state, read_journal=read_journal, web_dir=WEB_DIR):
    app = FastAPI(title="heating_web")

    def read_json(key):
        message = redis.get(key)
        return None if message is None else loads(message)

    def read_int(key):
        message = redis.get(key)
        try:
            return None if message is None else int(message)
        except ValueError:
            return None

    def read_reading(path):
        data = read_json(f"{path}/current_temperature")
        if data is None:
            return None
        return Reading(value=data["value"], time=data["time"], age_seconds=age_of(data["time"]))

    def read_zone(zone):
        path = zone.sensor_path
        reading = read_reading(path)
        target = read_json(f"{path}/target_temperature")
        control = redis.get(f"{path}/{CONTROL_VALUE}")
        return ZoneLive(
            name=zone.name,
            system=zone.system,
            sensor_path=path,
            current_temperature=reading,
            sensor_stale=reading is None or reading.age_seconds is None or reading.age_seconds > STALE_AFTER,
            target_temperature=None if target is None else target["value"],
            target_state=read_int(f"{path}/target_heatingcooling_state"),
            control_value=None if control is None else float(control),
            heating_cooling_state=read_int(f"{path}/heating_cooling_state"),
            boost=read_json(f"{path}/boost"),
            active=read_json(f"heating/{ACTIVE}/zones/{zone.name}"),
            shadow=read_json(f"heating/{SHADOW}/zones/{zone.name}"),
        )

    @app.get("/api/live", response_model=List[ZoneLive])
    def live():
        return [read_zone(zone) for zone in zones]

    @app.get("/api/services", response_model=List[ServiceState])
    def services():
        return [ServiceState(name=name, state=unit_state(name)) for name in SERVICES]

    @app.get("/api/logs", response_model=List[LogEntry])
    def logs(unit: Optional[str] = None, lines: int = Query(100, ge=1, le=MAX_LOG_LINES)):
        if unit is not None and unit not in SERVICES:
            raise HTTPException(status_code=422, detail=f"unit must be one of {list(SERVICES)}")
        try:
            return read_journal([unit] if unit else list(SERVICES), lines)
        except JournalError as error:
            raise HTTPException(status_code=503, detail=f"journal unavailable: {error}")

    def read_versions():
        entries = {}
        try:
            for key in redis.scan_iter(match=f"{VERSIONS_PREFIX}*"):
                service = key.decode("utf-8")[len(VERSIONS_PREFIX):]
                try:
                    data = loads(redis.get(key))
                    entries[service] = VersionEntry(service=service, version=str(data["version"]),
                                                    commit=str(data["commit"]), time=str(data["time"]))
                except (TypeError, ValueError, KeyError):
                    continue
        except RedisError:
            pass
        entries[SERVICE_NAME] = VersionEntry(service=SERVICE_NAME, **own_version)
        return [entries[name] for name in sorted(entries)]

    @app.get("/api/versions", response_model=List[VersionEntry])
    def versions():
        return read_versions()

    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return app
