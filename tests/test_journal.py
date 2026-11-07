import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from heating_web import journal
from heating_web.app import MAX_LOG_LINES, SERVICES, create_app
from heating_web.journal import JournalError, parse_entry, read_journal
from boiler_relay.config import SystemConfig

CONFIG = {
  "redis": {"host": "localhost", "port": 6379},
  "boiler": {"output_gpio": "P8_18"},
  "zones": [{
    "sensor_path": "/home/sensors/a",
    "name": "Bedrooms",
    "system": "hydronic",
    "outputs": [{"type": "gpio", "pin": "P8_10", "end_switch": "P8_9"}],
    "pid_interval": 10,
  }],
}


def line(**fields):
  entry = {"__REALTIME_TIMESTAMP": "1762520000000000", "_SYSTEMD_UNIT": "boiler_relay_v2.service",
           "PRIORITY": "6", "MESSAGE": "zone Bedrooms None -> HEAT"}
  entry.update(fields)
  return json.dumps(entry)


def completed(stdout="", returncode=0, stderr=""):
  return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


class Commands(list):
  def __init__(self):
    super().__init__()
    self.results = {"value": completed()}


@pytest.fixture
def commands(monkeypatch):
  seen = Commands()

  def run(command, **kwargs):
    seen.append(command)
    value = seen.results["value"]
    if isinstance(value, Exception):
      raise value
    return value

  monkeypatch.setattr(journal.subprocess, "run", run)
  return seen


def test_an_entry_is_parsed_into_time_unit_priority_and_message():
  entry = parse_entry(line())

  assert entry == {"time": "2025-11-07T12:53:20Z", "unit": "boiler_relay_v2",
                   "priority": 6, "message": "zone Bedrooms None -> HEAT"}


def test_the_unit_falls_back_to_the_unit_field_of_a_systemd_message():
  entry = parse_entry(line(_SYSTEMD_UNIT="init.scope", UNIT="boiler_relay.service", MESSAGE="Started"))

  assert entry["unit"] == "boiler_relay"


def test_a_binary_message_is_decoded():
  assert parse_entry(line(MESSAGE=[104, 105]))["message"] == "hi"


def test_a_missing_priority_and_message_are_tolerated():
  entry = parse_entry(json.dumps({"__REALTIME_TIMESTAMP": "1762520000000000"}))

  assert entry["priority"] is None
  assert entry["message"] == ""
  assert entry["unit"] is None


def test_read_journal_asks_for_each_unit_and_the_line_count(commands):
  commands.results["value"] = completed(line() + "\n" + line(MESSAGE="two") + "\n")

  entries = read_journal(["boiler_relay_v2", "mqtt_bridge"], 50)

  assert [e["message"] for e in entries] == ["zone Bedrooms None -> HEAT", "two"]
  assert commands[0] == ["journalctl", "--no-pager", "-o", "json", "-n", "50",
                         "-u", "boiler_relay_v2.service", "-u", "mqtt_bridge.service"]


def test_a_failed_journalctl_raises(commands):
  commands.results["value"] = completed(returncode=1, stderr="No journal files were found.")

  with pytest.raises(JournalError, match="No journal files"):
    read_journal(["mqtt_bridge"], 10)


@pytest.mark.parametrize("error", [FileNotFoundError("journalctl"), subprocess.TimeoutExpired("journalctl", 10)])
def test_a_missing_or_stuck_journalctl_raises(commands, error):
  commands.results["value"] = error

  with pytest.raises(JournalError):
    read_journal(["mqtt_bridge"], 10)


@pytest.fixture
def requests_seen():
  return []


@pytest.fixture
def client(redis_client, requests_seen):
  def fake(units, lines):
    requests_seen.append((units, lines))
    return [{"time": "2025-11-07T12:53:20Z", "unit": units[0], "priority": 6, "message": "hello"}]

  return TestClient(create_app(SystemConfig.from_dict(CONFIG), redis_client, read_journal=fake))


def test_logs_defaults_to_every_service_and_a_hundred_lines(client, requests_seen):
  response = client.get("/api/logs")

  assert response.status_code == 200
  assert requests_seen == [(list(SERVICES), 100)]
  assert response.json()[0]["message"] == "hello"


def test_logs_can_name_one_unit_and_a_line_count(client, requests_seen):
  client.get("/api/logs", params={"unit": "mqtt_bridge", "lines": 7})

  assert requests_seen == [(["mqtt_bridge"], 7)]


@pytest.mark.parametrize("params", [{"unit": "sshd"}, {"unit": "../../etc/passwd"}, {"lines": 0}, {"lines": MAX_LOG_LINES + 1}])
def test_logs_rejects_an_unknown_unit_and_bad_line_counts(client, requests_seen, params):
  assert client.get("/api/logs", params=params).status_code == 422
  assert requests_seen == []


def test_logs_reports_an_unavailable_journal_as_503(redis_client):
  def broken(units, lines):
    raise JournalError("no access")

  client = TestClient(create_app(SystemConfig.from_dict(CONFIG), redis_client, read_journal=broken))

  response = client.get("/api/logs")

  assert response.status_code == 503
  assert "no access" in response.json()["detail"]
