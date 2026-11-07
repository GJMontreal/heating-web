import logging
from datetime import datetime, timezone
from json import dumps, load
from pathlib import Path

from heating_web.contract import SERVICE_NAME, TIME_FORMAT, VERSIONS_PREFIX

log = logging.getLogger(__name__)

__version__ = "0.5.0"

BUILD_INFO = Path(__file__).resolve().parent.parent / "build_info.json"
UNKNOWN = "unknown"


def read_commit(path=BUILD_INFO):
    try:
        with open(path, "r") as file:
            commit = load(file)["commit"]
    except FileNotFoundError:
        return UNKNOWN
    except (OSError, ValueError, KeyError, TypeError) as error:
        log.warning("cannot read the commit from %s: %s", path, error)
        return UNKNOWN
    return commit if isinstance(commit, str) and commit else UNKNOWN


def describe(path=BUILD_INFO):
    return f"heating_web {__version__} ({read_commit(path)})"


def build_entry(path=BUILD_INFO):
    return {
        "version": __version__,
        "commit": read_commit(path),
        "time": datetime.now(timezone.utc).strftime(TIME_FORMAT),
    }


def publish_version(redis, entry):
    redis.set(f"{VERSIONS_PREFIX}{SERVICE_NAME}", dumps(entry))
