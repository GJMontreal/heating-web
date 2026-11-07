import subprocess
from datetime import datetime, timezone
from json import loads

from boiler_relay.state_publisher import TIME_FORMAT

JOURNAL_TIMEOUT = 10
SUFFIX = ".service"


class JournalError(Exception):
    pass


def read_journal(units, lines):
    command = ["journalctl", "--no-pager", "-o", "json", "-n", str(lines)]
    for unit in units:
        command += ["-u", f"{unit}{SUFFIX}"]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, timeout=JOURNAL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise JournalError(str(error))
    if result.returncode != 0:
        raise JournalError(result.stderr.strip() or f"journalctl exited {result.returncode}")
    return [parse_entry(line) for line in result.stdout.splitlines() if line.strip()]


def parse_entry(line):
    entry = loads(line)
    return {
        "time": entry_time(entry),
        "unit": entry_unit(entry),
        "priority": entry_priority(entry),
        "message": entry_message(entry),
    }


def entry_time(entry):
    microseconds = int(entry["__REALTIME_TIMESTAMP"])
    return datetime.fromtimestamp(microseconds / 1_000_000, timezone.utc).strftime(TIME_FORMAT)


def entry_unit(entry):
    unit = entry.get("_SYSTEMD_UNIT")
    if not unit or not unit.endswith(SUFFIX):
        unit = entry.get("UNIT")
    if unit and unit.endswith(SUFFIX):
        return unit[:-len(SUFFIX)]
    return unit


def entry_priority(entry):
    try:
        return int(entry["PRIORITY"])
    except (KeyError, ValueError):
        return None


def entry_message(entry):
    message = entry.get("MESSAGE")
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        return bytes(message).decode("utf-8", "replace")
    return ""
