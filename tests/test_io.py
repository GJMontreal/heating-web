import pytest
from fastapi.testclient import TestClient

from heating_web.app import create_app
from heating_web.gpio import PIN_NUMBERS
from heating_web.zones import Boiler, Output, Zone

OWN_VERSION = {"version": "0.3.0", "commit": "abc1234", "time": "2025-11-07T12:00:00Z"}
KITCHEN = Zone("Kitchen", "/home/sensors/k", "hydronic", [Output("gpio", "P8_16", "P8_7")], True)
STAIRWELL = Zone("Stairwell", "/home/sensors/s", "electric", [Output("MQTTRelay", None, None)], False)


class Clock:
  def __init__(self):
    self.value = "2026-11-07T12:00:00Z"

  def __call__(self):
    return self.value


@pytest.fixture
def clock():
  return Clock()


@pytest.fixture
def root(tmp_path):
  return tmp_path


def setpin(root, pin, level):
  directory = root / f"gpio{PIN_NUMBERS[pin]}"
  directory.mkdir(exist_ok=True)
  (directory / "value").write_text(f"{level}\n")


@pytest.fixture
def make(redis_client, root, clock):
  def build(zones, boiler=Boiler("P8_18", True)):
    app = create_app(zones, redis_client, OWN_VERSION, boiler=boiler, gpio_root=str(root), clock=clock)
    return TestClient(app)
  return build


def io(client):
  response = client.get("/api/io")
  assert response.status_code == 200
  return response.json()


def valve(client):
  return io(client)["zones"][0]


def test_an_active_low_valve_output_is_active_at_level_zero(make, root):
  setpin(root, "P8_16", 0)
  setpin(root, "P8_7", 0)

  output = valve(make([KITCHEN]))["outputs"][0]

  assert (output["pin"], output["level"], output["active"], output["exported"]) == ("P8_16", 0, True, True)


def test_an_active_low_valve_output_is_inactive_at_level_one(make, root):
  setpin(root, "P8_16", 1)

  assert valve(make([KITCHEN]))["outputs"][0]["active"] is False


def test_an_active_high_valve_output_is_active_at_level_one(make, root):
  zone = Zone("Kitchen", "/home/sensors/k", "hydronic", [Output("gpio", "P8_16", "P8_7")], False)
  setpin(root, "P8_16", 1)

  assert valve(make([zone]))["outputs"][0]["active"] is True


def test_an_end_switch_at_level_one_is_high_and_means_the_valve_is_open(make, root):
  setpin(root, "P8_7", 1)

  switch = valve(make([KITCHEN]))["end_switches"][0]

  assert (switch["pin"], switch["level"], switch["high"]) == ("P8_7", 1, True)


def test_an_end_switch_at_level_zero_is_low(make, root):
  setpin(root, "P8_7", 0)

  assert valve(make([KITCHEN]))["end_switches"][0]["high"] is False


def test_an_output_names_the_end_switch_it_is_paired_with(make):
  assert valve(make([KITCHEN]))["outputs"][0]["end_switch"] == "P8_7"


def test_the_boiler_is_on_when_its_active_low_pin_reads_zero(make, root):
  setpin(root, "P8_18", 0)

  assert io(make([KITCHEN]))["boiler"] == {"pin": "P8_18", "exported": True, "level": 0, "active": True, "on": True}


def test_the_boiler_is_off_when_its_active_low_pin_reads_one(make, root):
  setpin(root, "P8_18", 1)

  boiler = io(make([KITCHEN]))["boiler"]

  assert (boiler["active"], boiler["on"]) == (False, False)


def test_a_boiler_with_active_low_off_is_on_at_level_one(make, root):
  setpin(root, "P8_18", 1)

  assert io(make([KITCHEN], Boiler("P8_18", False)))["boiler"]["on"] is True


def test_no_boiler_section_gives_a_null_boiler(make):
  assert io(make([KITCHEN], boiler=None))["boiler"] is None


def test_a_pin_that_is_not_exported_has_a_null_level_and_is_not_an_error(make):
  data = io(make([KITCHEN]))

  assert data["boiler"] == {"pin": "P8_18", "exported": False, "level": None, "active": None, "on": None}
  assert data["zones"][0]["outputs"][0]["level"] is None
  assert data["zones"][0]["outputs"][0]["active"] is None
  assert data["zones"][0]["outputs"][0]["exported"] is False
  assert data["zones"][0]["end_switches"][0]["high"] is None


def test_an_electric_zone_has_an_unconfirmed_relay_and_no_pins(make):
  zone = make([STAIRWELL]).get("/api/io").json()["zones"][0]

  assert zone["outputs"] == [{"type": "mqtt", "state": "unconfirmed"}]
  assert zone["end_switches"] == []
  assert zone["system"] == "electric"


def test_a_zone_without_configured_outputs_has_null_outputs_and_switches(make):
  zone = valve(make([Zone("Bedrooms", "/home/sensors/b", "hydronic")]))

  assert zone["outputs"] is None
  assert zone["end_switches"] is None


def test_a_zone_with_two_valves_lists_both_pairs_in_order(make, root):
  bedrooms = Zone("Bedrooms", "/home/sensors/b", "hydronic",
                  [Output("gpio", "P8_10", "P8_9"), Output("gpio", "P8_14", "P8_17")], True)

  zone = valve(make([bedrooms]))

  assert [(o["pin"], o["end_switch"]) for o in zone["outputs"]] == [("P8_10", "P8_9"), ("P8_14", "P8_17")]
  assert [s["pin"] for s in zone["end_switches"]] == ["P8_9", "P8_17"]


def test_an_output_without_an_end_switch_adds_no_switch_entry(make, root):
  zone = Zone("Kitchen", "/home/sensors/k", "hydronic", [Output("gpio", "P8_16", None)], True)

  data = valve(make([zone]))

  assert data["outputs"][0]["end_switch"] is None
  assert data["end_switches"] == []


def test_the_response_carries_the_server_time(make, clock):
  assert io(make([KITCHEN]))["time"] == clock.value


def test_since_is_null_until_a_change_is_seen(make, root):
  setpin(root, "P8_7", 0)
  client = make([KITCHEN])

  assert valve(client)["end_switches"][0]["since"] is None
  assert valve(client)["end_switches"][0]["since"] is None


def test_since_is_the_time_the_change_was_first_seen_and_then_holds(make, root, clock):
  setpin(root, "P8_7", 0)
  client = make([KITCHEN])
  valve(client)

  clock.value = "2026-11-07T12:05:00Z"
  setpin(root, "P8_7", 1)
  assert valve(client)["end_switches"][0]["since"] == "2026-11-07T12:05:00Z"

  clock.value = "2026-11-07T12:09:00Z"
  assert valve(client)["end_switches"][0]["since"] == "2026-11-07T12:05:00Z"

  clock.value = "2026-11-07T12:10:00Z"
  setpin(root, "P8_7", 0)
  assert valve(client)["end_switches"][0]["since"] == "2026-11-07T12:10:00Z"


def test_since_tracks_outputs_too(make, root, clock):
  setpin(root, "P8_16", 1)
  client = make([KITCHEN])
  valve(client)
  clock.value = "2026-11-07T12:01:00Z"
  setpin(root, "P8_16", 0)

  assert valve(client)["outputs"][0]["since"] == "2026-11-07T12:01:00Z"


def test_the_io_route_leaves_the_pin_files_untouched(make, root):
  setpin(root, "P8_16", 0)
  setpin(root, "P8_7", 1)
  setpin(root, "P8_18", 0)
  before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in root.rglob("value")}

  io(make([KITCHEN]))

  assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in root.rglob("value")} == before


def test_the_io_route_accepts_only_get(make):
  assert make([KITCHEN]).post("/api/io").status_code == 405
