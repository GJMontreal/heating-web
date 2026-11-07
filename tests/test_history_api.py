import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from heating_web.app import create_app
from heating_web.history import DATABASE, WINDOW_SECONDS, History
from heating_web.history_reader import HistoryReader
from heating_web.sampler import DATA_FOLDER
from heating_web.zones import Zone

NOW = 1_800_000_000 - (1_800_000_000 % WINDOW_SECONDS) + 125
OWN_VERSION = {"version": "0.5.0", "commit": "abc1234", "time": "2025-11-07T12:00:00Z"}
BEDROOMS = Zone("Bedrooms", "/home/sensors/b", "hydronic")
STAIRWELL = Zone("Stairwell", "/home/sensors/s", "electric")
ZONES = [BEDROOMS, STAIRWELL]


@pytest.fixture
def root(tmp_path):
  (tmp_path / DATA_FOLDER).mkdir()
  return tmp_path


@pytest.fixture
def mounted():
  return {"value": True}


@pytest.fixture
def history(root):
  opened = History(str(root / DATA_FOLDER / DATABASE))
  yield opened
  opened.close()


@pytest.fixture
def client(redis_client, root, mounted):
  reader = HistoryReader(str(root), is_mounted=lambda path: mounted["value"], epoch=lambda: NOW)
  return TestClient(create_app(ZONES, redis_client, OWN_VERSION, history=reader))


def tree(root):
  return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def fill(history, start, count, zone="Bedrooms", step=10, **values):
  for index in range(count):
    history.add(start + index * step, zone, **{name: value(index) if callable(value) else value
                                               for name, value in values.items()})
  history.commit()


def history_of(client, **params):
  response = client.get("/api/history", params=params)
  assert response.status_code == 200, response.text
  return response.json()


def by_name(data):
  return {zone["name"]: zone for zone in data["zones"]}


def test_history_returns_columns_with_nulls_passed_through(client, history):
  fill(history, NOW - 100, 3, temp=lambda i: [19.5, None, 20.0][i], ctl=0.4, sh_ctl=0.35, hc=1, sh_state=1)

  zone = by_name(history_of(client, hours=1))["Bedrooms"]

  assert zone["t"] == [NOW - 100, NOW - 90, NOW - 80]
  assert zone["temp"] == [19.5, None, 20.0]
  assert zone["ctl"] == [0.4, 0.4, 0.4]
  assert zone["sh_ctl"] == [0.35, 0.35, 0.35]
  assert zone["hc"] == [1.0, 1.0, 1.0]


def test_history_rounds_temperatures_to_two_decimals_and_fractions_to_three(client, history):
  fill(history, NOW - 50, 1, temp=21.22000000000002, target=20.123456, ctl=0.123456789, sh_ctl=0.9999999)

  zone = by_name(history_of(client, hours=1))["Bedrooms"]

  assert (zone["temp"], zone["target"]) == ([21.22], [20.12])
  assert (zone["ctl"], zone["sh_ctl"]) == ([0.123], [1.0])


def test_a_zone_without_legacy_values_is_flagged_not_zeroed(client, history):
  fill(history, NOW - 100, 3, zone="Stairwell", temp=16.0, sh_ctl=0.2, sh_state=0)

  zone = by_name(history_of(client, hours=1))["Stairwell"]

  assert zone["legacy_available"] is False
  assert zone["ctl"] == [None, None, None]
  assert zone["sh_ctl"] == [0.2, 0.2, 0.2]


def test_a_zone_with_legacy_values_is_flagged_available(client, history):
  fill(history, NOW - 100, 2, ctl=0.0, hc=0)

  assert by_name(history_of(client, hours=1))["Bedrooms"]["legacy_available"] is True


def test_a_configured_zone_with_no_rows_returns_empty_columns(client, history):
  zone = by_name(history_of(client, hours=1))["Bedrooms"]

  assert zone["t"] == [] and zone["temp"] == []
  assert zone["legacy_available"] is False


def test_only_samples_inside_the_range_are_returned(client, history):
  fill(history, NOW - 7200, 2, ctl=0.1)
  fill(history, NOW - 100, 2, ctl=0.2)

  zone = by_name(history_of(client, hours=1))["Bedrooms"]

  assert zone["ctl"] == [0.2, 0.2]


def test_a_long_range_is_downsampled_to_about_the_requested_points(client, history):
  fill(history, NOW - 6 * 3600, 2160, ctl=lambda i: (i % 10) / 10)

  data = history_of(client, hours=6, points=100)

  zone = by_name(data)["Bedrooms"]
  assert data["bucket_seconds"] == 216
  assert 90 <= len(zone["t"]) <= 101
  assert all(0 <= value <= 1 for value in zone["ctl"])


def test_a_short_range_keeps_the_raw_rows(client, history):
  fill(history, NOW - 300, 30, ctl=0.5)

  data = history_of(client, hours=1, points=1000)

  assert data["bucket_seconds"] == 1
  assert len(by_name(data)["Bedrooms"]["t"]) == 30


def test_one_zone_can_be_asked_for(client, history):
  data = history_of(client, zone="Stairwell", hours=1)

  assert [zone["name"] for zone in data["zones"]] == ["Stairwell"]


def test_an_unknown_zone_is_a_404(client):
  assert client.get("/api/history", params={"zone": "Nope"}).status_code == 404
  assert client.get("/api/compare", params={"zone": "Nope"}).status_code == 404


@pytest.mark.parametrize("params", [{"hours": 0}, {"hours": 169}, {"points": 9}, {"points": 1001}])
def test_out_of_range_parameters_are_rejected(client, params):
  assert client.get("/api/history", params=params).status_code == 422


def make_window(history, start, count, on, shadow_on=None, ctl=0.5, sh_ctl=0.5, zone="Bedrooms", **extra):
  for index in range(count):
    history.add(start + index * 10, zone, temp=20.0, target=21.0, ctl=ctl, sh_ctl=sh_ctl,
                hc=1 if index < on else 0, sh_state=None if shadow_on is None else (1 if index < shadow_on else 0), **extra)
  history.commit()


def compare_of(client, **params):
  response = client.get("/api/compare", params=params)
  assert response.status_code == 200, response.text
  return response.json()


def test_a_window_with_the_output_on_for_part_of_it_has_that_on_fraction(client, history):
  start = NOW - 2 * WINDOW_SECONDS - 125
  make_window(history, start, 60, on=20, shadow_on=30)
  history.aggregate(NOW)
  history.commit()

  zone = by_name(compare_of(client))["Bedrooms"]

  assert zone["windows"]["n"] == [60]
  assert zone["windows"]["on_fraction"] == [0.333]
  assert zone["windows"]["sh_on_fraction"] == [0.5]
  assert zone["summary"]["on_fraction"] == 0.333
  assert zone["summary"]["sh_on_fraction"] == 0.5


def test_compare_gives_legacy_and_shadow_means_side_by_side(client, history):
  start = NOW - 3 * WINDOW_SECONDS - 125
  make_window(history, start, 60, on=0, ctl=0.2, sh_ctl=0.1)
  make_window(history, start + WINDOW_SECONDS, 60, on=0, ctl=0.4, sh_ctl=0.3)
  history.aggregate(NOW)
  history.commit()

  zone = by_name(compare_of(client))["Bedrooms"]

  assert zone["windows"]["ctl"] == [0.2, 0.4]
  assert zone["windows"]["sh_ctl"] == [0.1, 0.3]
  assert zone["summary"] == {"windows": 2, "ctl": 0.3, "sh_ctl": 0.2, "on_fraction": 0.0, "sh_on_fraction": None}


def test_compare_flags_a_zone_with_no_legacy_side(client, history):
  start = NOW - 2 * WINDOW_SECONDS - 125
  for index in range(60):
    history.add(start + index * 10, "Stairwell", temp=16.0, sh_ctl=0.2, sh_state=0)
  history.commit()
  history.aggregate(NOW)
  history.commit()

  zone = by_name(compare_of(client))["Stairwell"]

  assert zone["legacy_available"] is False
  assert zone["windows"]["ctl"] == [None]
  assert zone["summary"]["ctl"] is None
  assert zone["summary"]["sh_ctl"] == 0.2


def test_compare_defaults_to_the_last_24_hours_and_accepts_longer_ranges(client, history):
  old = NOW - 30 * 3600
  make_window(history, old - old % WINDOW_SECONDS, 60, on=0)
  recent = NOW - 2 * WINDOW_SECONDS - 125
  make_window(history, recent, 60, on=0)
  history.aggregate(NOW)
  history.commit()

  assert by_name(compare_of(client))["Bedrooms"]["summary"]["windows"] == 1
  assert by_name(compare_of(client, hours=48))["Bedrooms"]["summary"]["windows"] == 2


def test_compare_rounds_window_means(client, history):
  start = NOW - 2 * WINDOW_SECONDS - 125
  make_window(history, start, 60, on=0, ctl=0.1234567, sh_ctl=0.7654321)
  history.aggregate(NOW)
  history.commit()

  zone = by_name(compare_of(client))["Bedrooms"]

  assert zone["windows"]["temp"] == [20.0]
  assert zone["windows"]["ctl"] == [0.123]
  assert zone["windows"]["sh_ctl"] == [0.765]


def test_out_of_range_compare_hours_are_rejected(client):
  assert client.get("/api/compare", params={"hours": 0}).status_code == 422
  assert client.get("/api/compare", params={"hours": 337}).status_code == 422


@pytest.mark.parametrize("route", ["/api/history", "/api/compare"])
def test_an_unmounted_card_gives_a_503_and_creates_nothing(client, root, mounted, route):
  mounted["value"] = False
  before = tree(root)

  response = client.get(route)

  assert response.status_code == 503
  assert "not a mount point" in response.json()["detail"]
  assert tree(root) == before


@pytest.mark.parametrize("route", ["/api/history", "/api/compare"])
def test_a_missing_database_gives_a_503_and_is_not_created(client, root, route):
  before = tree(root)

  response = client.get(route)

  assert response.status_code == 503
  assert "does not exist" in response.json()["detail"]
  assert tree(root) == before


def test_a_missing_data_folder_gives_a_503_and_is_not_created(redis_client, tmp_path):
  reader = HistoryReader(str(tmp_path), is_mounted=lambda path: True, epoch=lambda: NOW)
  client = TestClient(create_app(ZONES, redis_client, OWN_VERSION, history=reader))

  assert client.get("/api/history").status_code == 503
  assert tree(tmp_path) == []


def test_a_corrupt_database_gives_a_503(client, root):
  (root / DATA_FOLDER / DATABASE).write_bytes(b"this is not a database" * 100)

  assert client.get("/api/history").status_code == 503


def test_the_reader_cannot_write(root, history):
  reader = HistoryReader(str(root), is_mounted=lambda path: True)
  connection = reader.connect()

  with pytest.raises(sqlite3.OperationalError, match="readonly"):
    connection.execute("INSERT INTO zones (name) VALUES ('x')")
  connection.close()


def test_reading_leaves_the_database_and_its_log_unchanged(client, root, history):
  fill(history, NOW - 100, 5, ctl=0.5)
  paths = [root / DATA_FOLDER / name for name in os.listdir(str(root / DATA_FOLDER)) if not name.endswith("-shm")]
  before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}

  history_of(client, hours=1)
  compare_of(client)

  assert {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == before


def test_the_routes_accept_only_get(client):
  assert client.post("/api/history").status_code == 405
  assert client.post("/api/compare").status_code == 405
