import json

import pytest

from heating_web.zones import Boiler, Output, Zone, ZonesError, load_config


def write(tmp_path, content):
  path = tmp_path / "system_config.json"
  path.write_text(content if isinstance(content, str) else json.dumps(content))
  return str(path)


def minimal(**fields):
  return {"name": "A", "sensor_path": "/x", "system": "hydronic", **fields}


def test_a_zone_keeps_its_identity_outputs_and_polarity_and_drops_the_rest(tmp_path):
  path = write(tmp_path, {
    "redis": {"host": "localhost", "port": 6379},
    "zones": [{"name": "Bedrooms", "sensor_path": "/home/sensors/a", "system": "hydronic",
               "outputs": [{"type": "gpio", "pin": "P8_10", "end_switch": "P8_9"},
                           {"type": "gpio", "pin": "P8_14"}],
               "active_low": True, "pid_interval": 10, "unknown_key": 1}],
  })

  assert load_config(path).zones == [Zone("Bedrooms", "/home/sensors/a", "hydronic", [
    Output("gpio", "P8_10", "P8_9"), Output("gpio", "P8_14", None)], True)]


def test_an_electric_zone_output_has_no_pin(tmp_path):
  path = write(tmp_path, {"zones": [minimal(system="electric", outputs=[{"type": "MQTTRelay", "topic": "t", "device": "d"}])]})

  assert load_config(path).zones[0].outputs == [Output("MQTTRelay", None, None)]


def test_nothing_is_validated_beyond_the_three_identity_fields(tmp_path):
  path = write(tmp_path, {"zones": [minimal(system="steam")]})

  assert load_config(path).zones[0].system == "steam"


def test_a_file_without_outputs_gives_null_for_outputs_and_polarity(tmp_path):
  path = write(tmp_path, {"zones": [minimal()]})

  zone = load_config(path).zones[0]

  assert zone.outputs is None
  assert zone.active_low is None


@pytest.mark.parametrize("outputs", [3, "P8_10", {"pin": "P8_10"}, [3], [{"pin": "P8_10"}, None]])
def test_malformed_outputs_give_null_not_a_crash(tmp_path, outputs):
  path = write(tmp_path, {"zones": [minimal(outputs=outputs)]})

  assert load_config(path).zones[0].outputs is None


def test_a_zone_with_outputs_defaults_active_low_to_false_like_the_control_service(tmp_path):
  path = write(tmp_path, {"zones": [minimal(outputs=[{"type": "gpio", "pin": "P8_10"}])]})

  assert load_config(path).zones[0].active_low is False


def test_the_boiler_defaults_active_low_to_true_like_the_control_service(tmp_path):
  path = write(tmp_path, {"zones": [], "boiler": {"output_gpio": "P8_18", "poll_interval": 5}})

  assert load_config(path).boiler == Boiler("P8_18", True)


def test_the_boiler_polarity_can_be_turned_off(tmp_path):
  path = write(tmp_path, {"zones": [], "boiler": {"output_gpio": "P8_18", "active_low": False}})

  assert load_config(path).boiler == Boiler("P8_18", False)


@pytest.mark.parametrize("boiler", [None, 3, {}, {"poll_interval": 5}, []])
def test_a_missing_or_unusable_boiler_section_gives_null(tmp_path, boiler):
  data = {"zones": []}
  if boiler is not None:
    data["boiler"] = boiler

  assert load_config(write(tmp_path, data)).boiler is None


def test_a_missing_file_is_a_clear_error(tmp_path):
  with pytest.raises(ZonesError, match="cannot read .*missing.json"):
    load_config(str(tmp_path / "missing.json"))


def test_an_unreadable_file_is_a_clear_error(tmp_path):
  with pytest.raises(ZonesError, match="cannot read"):
    load_config(str(tmp_path))


def test_invalid_json_is_a_clear_error(tmp_path):
  with pytest.raises(ZonesError, match="not valid JSON"):
    load_config(write(tmp_path, "{not json"))


@pytest.mark.parametrize("content", [{}, {"zones": 3}, {"zones": [{"name": "A"}]}, []])
def test_a_file_without_usable_zones_is_a_clear_error(tmp_path, content):
  with pytest.raises(ZonesError, match="no usable zones"):
    load_config(write(tmp_path, content))
