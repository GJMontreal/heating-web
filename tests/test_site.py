import json
import logging
import os

import pytest
from fastapi.testclient import TestClient

from heating_web import __main__ as entry
from heating_web.app import create_app
from heating_web.site import DEFAULT_NAME, MAX_LENGTH, SiteName, valid_name
from heating_web.zones import Zone, load_config

OWN_VERSION = {"version": "0.1.0", "commit": "abc1234", "time": "2025-11-07T12:00:00Z"}


@pytest.fixture
def site_file(tmp_path):
  return tmp_path / "site.json"


CLOCK = {"ns": 1_700_000_000_000_000_000}


def write(path, value):
  path.write_text(json.dumps({"site_name": value}))
  CLOCK["ns"] += 1_000_000_000
  os.utime(str(path), ns=(CLOCK["ns"], CLOCK["ns"]))


def test_with_no_file_and_no_config_the_name_is_the_default(site_file):
  assert SiteName(str(site_file)).name() == DEFAULT_NAME


def test_the_device_file_wins_over_the_config(site_file):
  write(site_file, "Example Site")

  assert SiteName(str(site_file), "Config Name").name() == "Example Site"


def test_the_config_name_is_used_without_a_device_file(site_file):
  assert SiteName(str(site_file), "Config Name").name() == "Config Name"


def test_a_name_is_stripped(site_file):
  write(site_file, "  Example Site \n")

  assert SiteName(str(site_file)).name() == "Example Site"


@pytest.mark.parametrize("value", ["", "   ", "x" * (MAX_LENGTH + 1), "bad\nname", "bad\x00name", "bad name",
                                   None, 5, ["a"], {"a": 1}])
def test_a_bad_name_is_rejected(value):
  assert valid_name(value) is None


def test_a_name_of_the_longest_allowed_length_is_accepted():
  assert valid_name("x" * MAX_LENGTH) == "x" * MAX_LENGTH


def test_a_bad_device_value_falls_through_to_the_config_and_warns_once(site_file, caplog):
  write(site_file, "leaky\nname")
  site = SiteName(str(site_file), "Config Name")

  with caplog.at_level(logging.WARNING):
    assert site.name() == "Config Name"
    assert site.name() == "Config Name"

  assert len([record for record in caplog.records if "site_name" in record.getMessage()]) == 1
  assert "leaky" not in caplog.text


def test_a_bad_config_value_falls_through_to_the_default_and_warns_once(site_file, caplog):
  with caplog.at_level(logging.WARNING):
    site = SiteName(str(site_file), "x" * 100)
    assert site.name() == DEFAULT_NAME
    assert site.name() == DEFAULT_NAME

  assert len(caplog.records) == 1


def test_a_file_that_is_not_json_falls_through(site_file):
  site_file.write_text("not json")

  assert SiteName(str(site_file), "Config Name").name() == "Config Name"


def test_a_file_without_the_key_falls_through(site_file):
  site_file.write_text(json.dumps({"other": "x"}))

  assert SiteName(str(site_file), "Config Name").name() == "Config Name"


def test_a_changed_file_is_read_again_without_a_restart(site_file):
  site = SiteName(str(site_file))
  write(site_file, "Example Site")
  assert site.name() == "Example Site"

  write(site_file, "Other Site")

  assert site.name() == "Other Site"


def test_an_unchanged_file_is_not_read_again(site_file, monkeypatch):
  write(site_file, "Example Site")
  site = SiteName(str(site_file))
  site.name()
  monkeypatch.setattr("builtins.open", lambda *args, **kwargs: pytest.fail("the file was read again"))

  assert site.name() == "Example Site"


def test_a_file_that_goes_away_falls_back(site_file):
  write(site_file, "Example Site")
  site = SiteName(str(site_file), "Config Name")
  assert site.name() == "Example Site"

  site_file.unlink()

  assert site.name() == "Config Name"


def test_an_unreadable_file_never_raises(site_file, monkeypatch):
  write(site_file, "Example Site")
  site = SiteName(str(site_file))

  def refuse(*args, **kwargs):
    raise PermissionError("no")

  monkeypatch.setattr("builtins.open", refuse)

  assert site.name() == DEFAULT_NAME


def test_a_directory_in_place_of_the_file_never_raises(tmp_path):
  assert SiteName(str(tmp_path)).name() == DEFAULT_NAME


@pytest.fixture
def client(redis_client, site_file):
  zones = [Zone("Bedrooms", "/home/sensors/a", "hydronic")]
  site = SiteName(str(site_file))
  return TestClient(create_app(zones, redis_client, OWN_VERSION, unit_state=lambda name: "inactive", site=site))


def test_the_route_returns_the_name(client, site_file):
  write(site_file, "Example Site")

  response = client.get("/api/site")

  assert response.status_code == 200
  assert response.json() == {"site_name": "Example Site"}


def test_the_route_returns_the_default_with_no_file(client):
  assert client.get("/api/site").json() == {"site_name": DEFAULT_NAME}


def test_the_route_accepts_only_get(client):
  assert client.post("/api/site").status_code == 405


def test_the_config_loader_reads_the_top_level_name(tmp_path):
  path = tmp_path / "system_config.json"
  path.write_text(json.dumps({"site_name": "Example Site",
                              "zones": [{"name": "Bedrooms", "sensor_path": "/s", "system": "hydronic"}]}))

  assert load_config(str(path)).site_name == "Example Site"


def test_the_config_loader_ignores_a_missing_name(tmp_path):
  path = tmp_path / "system_config.json"
  path.write_text(json.dumps({"zones": [{"name": "Bedrooms", "sensor_path": "/s", "system": "hydronic"}]}))

  assert load_config(str(path)).site_name is None


def test_the_site_file_flag_has_a_default_and_can_be_set():
  assert entry.parse_arguments([]).site_file == "/etc/heating/site.json"
  assert entry.parse_arguments(["--site-file", "/tmp/s.json"]).site_file == "/tmp/s.json"
