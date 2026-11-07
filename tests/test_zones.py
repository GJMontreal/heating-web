import json

import pytest

from heating_web.zones import Zone, ZonesError, load_zones


def write(tmp_path, content):
  path = tmp_path / "system_config.json"
  path.write_text(content if isinstance(content, str) else json.dumps(content))
  return str(path)


def test_zones_keep_only_the_name_the_sensor_path_and_the_system(tmp_path):
  path = write(tmp_path, {
    "redis": {"host": "localhost", "port": 6379},
    "zones": [{"name": "Bedrooms", "sensor_path": "/home/sensors/a", "system": "hydronic",
               "outputs": [], "pid_interval": 10, "unknown_key": 1}],
  })

  assert load_zones(path) == [Zone("Bedrooms", "/home/sensors/a", "hydronic")]


def test_nothing_is_validated_beyond_the_three_fields(tmp_path):
  path = write(tmp_path, {"zones": [{"name": "A", "sensor_path": "/x", "system": "steam"}]})

  assert load_zones(path)[0].system == "steam"


def test_a_missing_file_is_a_clear_error(tmp_path):
  with pytest.raises(ZonesError, match="cannot read .*missing.json"):
    load_zones(str(tmp_path / "missing.json"))


def test_an_unreadable_file_is_a_clear_error(tmp_path):
  with pytest.raises(ZonesError, match="cannot read"):
    load_zones(str(tmp_path))


def test_invalid_json_is_a_clear_error(tmp_path):
  with pytest.raises(ZonesError, match="not valid JSON"):
    load_zones(write(tmp_path, "{not json"))


@pytest.mark.parametrize("content", [{}, {"zones": 3}, {"zones": [{"name": "A"}]}, []])
def test_a_file_without_usable_zones_is_a_clear_error(tmp_path, content):
  with pytest.raises(ZonesError, match="no usable zones"):
    load_zones(write(tmp_path, content))
