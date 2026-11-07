import json
import re

import pytest

from heating_web import version


def test_the_version_is_semantic():
  assert re.fullmatch(r"\d+\.\d+\.\d+", version.__version__)


def test_the_commit_is_read_from_the_build_file(tmp_path):
  path = tmp_path / "build_info.json"
  path.write_text(json.dumps({"version": "0.1.0", "commit": "abc1234-dirty"}))

  assert version.read_commit(path) == "abc1234-dirty"


def test_a_missing_build_file_gives_an_unknown_commit(tmp_path):
  assert version.read_commit(tmp_path / "missing.json") == "unknown"


@pytest.mark.parametrize("content", ["not json", "[]", "{}", '{"commit": null}'])
def test_an_unreadable_build_file_gives_an_unknown_commit(tmp_path, content):
  path = tmp_path / "build_info.json"
  path.write_text(content)

  assert version.read_commit(path) == "unknown"


def test_describe_names_the_package_version_and_commit(tmp_path):
  path = tmp_path / "build_info.json"
  path.write_text(json.dumps({"commit": "abc1234"}))

  assert version.describe(path) == f"heating_web {version.__version__} (abc1234)"


def test_the_entry_has_the_version_the_commit_and_the_start_time(tmp_path):
  path = tmp_path / "build_info.json"
  path.write_text(json.dumps({"commit": "abc1234"}))

  entry = version.build_entry(path)

  assert set(entry) == {"version", "commit", "time"}
  assert entry["version"] == version.__version__
  assert entry["commit"] == "abc1234"
  assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", entry["time"])


def test_publish_version_sets_the_key_without_publishing(redis_client):
  entry = {"version": "0.1.0", "commit": "abc1234", "time": "2025-11-07T12:00:00Z"}
  channel = redis_client.pubsub()
  channel.subscribe("heating/versions/heating-web")
  channel.get_message()

  version.publish_version(redis_client, entry)

  assert json.loads(redis_client.get("heating/versions/heating-web")) == entry
  assert channel.get_message() is None
