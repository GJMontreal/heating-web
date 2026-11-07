import json
import logging

import fakeredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from heating_web import __main__ as entry
from heating_web import version


@pytest.fixture
def zones_file(tmp_path):
  path = tmp_path / "system_config.json"
  path.write_text(json.dumps({"zones": [{"name": "Bedrooms", "sensor_path": "/home/sensors/a", "system": "hydronic"}]}))
  return str(path)


@pytest.fixture
def served(monkeypatch, redis_server):
  calls = []
  monkeypatch.setattr(entry, "Redis", lambda **kwargs: fakeredis.FakeRedis(server=redis_server))
  monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
  return calls


def test_the_defaults():
  args = entry.parse_arguments([])

  assert args.host == "127.0.0.1"
  assert args.port == 8080
  assert args.zones == "/var/lib/boiler_relay_v2/config/system_config.json"
  assert (args.redis_host, args.redis_port) == ("localhost", 6379)
  assert args.gpio_root == "/sys/class/gpio"


def test_the_flags_override_the_defaults():
  args = entry.parse_arguments(["--host", "0.0.0.0", "--port", "9000", "--zones", "z.json",
                                "--redis-host", "r", "--redis-port", "6380", "--gpio-root", "/tmp/g"])

  assert (args.host, args.port, args.zones) == ("0.0.0.0", 9000, "z.json")
  assert (args.redis_host, args.redis_port) == ("r", 6380)
  assert args.gpio_root == "/tmp/g"


def test_the_version_flag_prints_and_exits_zero(capsys):
  with pytest.raises(SystemExit) as exit_info:
    entry.parse_arguments(["--version"])

  assert exit_info.value.code == 0
  assert capsys.readouterr().out.startswith(f"heating_web {version.__version__} (")


def test_main_runs_uvicorn_with_the_host_and_port(zones_file, served):
  code = entry.main(["--zones", zones_file, "--host", "0.0.0.0", "--port", "9000"])

  assert code == 0
  assert served[0][1] == {"host": "0.0.0.0", "port": 9000}


def test_main_publishes_its_version(zones_file, served, redis_server):
  entry.main(["--zones", zones_file])

  data = json.loads(fakeredis.FakeRedis(server=redis_server).get("heating/versions/heating-web"))
  assert set(data) == {"version", "commit", "time"}
  assert data["version"] == version.__version__


def test_main_exits_two_on_a_missing_zones_file(tmp_path, served, caplog):
  with caplog.at_level(logging.ERROR, logger="heating_web"):
    code = entry.main(["--zones", str(tmp_path / "missing.json")])

  assert code == 2
  assert "invalid zones file" in caplog.text
  assert served == []


def test_main_runs_without_the_version_key_when_redis_is_down(zones_file, served, monkeypatch, caplog):
  def refuse(redis, value):
    raise RedisConnectionError("redis is down")

  monkeypatch.setattr(entry, "publish_version", refuse)

  with caplog.at_level(logging.WARNING, logger="heating_web"):
    code = entry.main(["--zones", zones_file])

  assert code == 0
  assert len(served) == 1
  assert "could not publish the version" in caplog.text


def test_main_reads_the_boiler_and_the_gpio_root_into_the_app(tmp_path, served):
  from fastapi.testclient import TestClient
  from heating_web.gpio import PIN_NUMBERS

  config = tmp_path / "system_config.json"
  config.write_text(json.dumps({
    "zones": [{"name": "Kitchen", "sensor_path": "/home/sensors/k", "system": "hydronic",
               "outputs": [{"type": "gpio", "pin": "P8_16", "end_switch": "P8_7"}]}],
    "boiler": {"output_gpio": "P8_18"},
  }))
  root = tmp_path / "gpio"
  (root / f"gpio{PIN_NUMBERS['P8_18']}").mkdir(parents=True)
  (root / f"gpio{PIN_NUMBERS['P8_18']}" / "value").write_text("0\n")

  entry.main(["--zones", str(config), "--gpio-root", str(root)])

  boiler = TestClient(served[0][0]).get("/api/io").json()["boiler"]
  assert (boiler["pin"], boiler["level"], boiler["on"]) == ("P8_18", 0, True)
