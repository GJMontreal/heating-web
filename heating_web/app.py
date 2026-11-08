import subprocess
from json import loads
from pathlib import Path
from typing import List, Optional, Union

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from redis.exceptions import RedisError

from heating_web.contract import SERVICE_NAME, VERSIONS_PREFIX
from heating_web.gpio import GPIO_ROOT, SysfsReader
from heating_web.history_reader import MAX_HOURS, MAX_WINDOW_HOURS, HistoryReader, HistoryUnavailable
from heating_web.io_state import IoView, utc_now
from heating_web.journal import JournalError, read_journal
from heating_web.live_state import ZoneLive, read_zone

SERVICES = ("boiler_relay", "boiler_relay_v2", "boiler_relay_v2_shadow", "mqtt_bridge")
SYSTEMCTL_TIMEOUT = 5
MAX_LOG_LINES = 500
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


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


class PinOutput(BaseModel):
    pin: str
    exported: bool
    level: Optional[int]
    active: Optional[bool]
    since: Optional[str]
    end_switch: Optional[str]


class MqttOutput(BaseModel):
    type: str
    state: str


class EndSwitch(BaseModel):
    pin: str
    exported: bool
    level: Optional[int]
    high: Optional[bool]
    since: Optional[str]


class ZoneIo(BaseModel):
    name: str
    system: str
    outputs: Optional[List[Union[PinOutput, MqttOutput]]]
    end_switches: Optional[List[EndSwitch]]


class BoilerIo(BaseModel):
    pin: str
    exported: bool
    level: Optional[int]
    active: Optional[bool]
    on: Optional[bool]


class IoState(BaseModel):
    time: str
    boiler: Optional[BoilerIo]
    zones: List[ZoneIo]


class SeriesZone(BaseModel):
    name: str
    system: str
    legacy_available: bool
    t: List[int]
    temp: List[Optional[float]]
    target: List[Optional[float]]
    ctl: List[Optional[float]]
    sh_ctl: List[Optional[float]]
    hc: List[Optional[float]]
    sh_state: List[Optional[float]]
    out: List[Optional[float]]
    sw: List[Optional[float]]


class BoilerSeries(BaseModel):
    t: List[int]
    on: List[Optional[float]]


class HistoryState(BaseModel):
    start: int
    end: int
    bucket_seconds: int
    zones: List[SeriesZone]
    boiler: BoilerSeries


class WindowColumns(BaseModel):
    start: List[int]
    n: List[int]
    temp: List[Optional[float]]
    target: List[Optional[float]]
    ctl: List[Optional[float]]
    sh_ctl: List[Optional[float]]
    on_fraction: List[Optional[float]]
    sh_on_fraction: List[Optional[float]]
    out_fraction: List[Optional[float]]
    sw_fraction: List[Optional[float]]


class BoilerWindows(BaseModel):
    start: List[int]
    n: List[int]
    on_fraction: List[Optional[float]]


class WindowSummary(BaseModel):
    windows: int
    ctl: Optional[float]
    sh_ctl: Optional[float]
    on_fraction: Optional[float]
    sh_on_fraction: Optional[float]


class ProfileChange(BaseModel):
    start: int
    pid: Optional[dict]


class LiveChange(BaseModel):
    start: int
    controller: Optional[str]
    pid: Optional[dict]


class CompareZone(BaseModel):
    name: str
    system: str
    legacy_available: bool
    windows: WindowColumns
    profiles: List[ProfileChange]
    live: List[LiveChange]
    summary: WindowSummary


class CompareState(BaseModel):
    start: int
    end: int
    zones: List[CompareZone]
    boiler: BoilerWindows


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


def create_app(zones, redis, own_version, unit_state=unit_state, read_journal=read_journal, web_dir=WEB_DIR,
               boiler=None, gpio_root=GPIO_ROOT, clock=utc_now, history=None):
    app = FastAPI(title="heating_web")
    io_view = IoView(zones, boiler, SysfsReader(gpio_root), clock)
    history = history or HistoryReader()

    def chosen(zone):
        if zone is None:
            return list(zones)
        found = [entry for entry in zones if entry.name == zone]
        if not found:
            raise HTTPException(status_code=404, detail=f"unknown zone {zone!r}")
        return found

    def unavailable(error):
        return HTTPException(status_code=503, detail=f"history unavailable: {error}")

    @app.get("/api/live", response_model=List[ZoneLive])
    def live():
        return [read_zone(redis, zone) for zone in zones]

    @app.get("/api/io", response_model=IoState)
    def io():
        return io_view.snapshot()

    @app.get("/api/history", response_model=HistoryState)
    def history_series(zone: Optional[str] = None, hours: int = Query(24, ge=1, le=MAX_HOURS),
                       points: int = Query(360, ge=10, le=1000)):
        try:
            return history.series(chosen(zone), hours, points)
        except HistoryUnavailable as error:
            raise unavailable(error)

    @app.get("/api/compare", response_model=CompareState)
    def compare(zone: Optional[str] = None, hours: int = Query(24, ge=1, le=MAX_WINDOW_HOURS)):
        try:
            return history.windows(chosen(zone), hours)
        except HistoryUnavailable as error:
            raise unavailable(error)

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
