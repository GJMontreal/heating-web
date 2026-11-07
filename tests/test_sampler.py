import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from heating_web.history import DATABASE
from heating_web.sampler import COMMIT_INTERVAL, DATA_FOLDER, SAMPLE_INTERVAL, Sampler
from heating_web.zones import Zone

SENSOR = "/home/sensors/a"
ZONES = [Zone("Bedrooms", SENSOR, "hydronic")]


def stamp(age=0):
  return (datetime.now(timezone.utc) - timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Clock:
  def __init__(self):
    self.value = 1_800_000_000.0

  def __call__(self):
    return self.value

  def advance(self, seconds):
    self.value += seconds


@pytest.fixture
def clock():
  return Clock()


@pytest.fixture
def mounted():
  return {"value": True}


@pytest.fixture
def root(tmp_path):
  (tmp_path / DATA_FOLDER).mkdir()
  return tmp_path


@pytest.fixture
def sampler(redis_client, root, clock, mounted):
  made = Sampler(redis_client, ZONES, root=str(root), is_mounted=lambda path: mounted["value"], clock=clock)
  yield made
  made.release()


def database(root):
  return sqlite3.connect(str(root / DATA_FOLDER / DATABASE))


def stored(root, sql="SELECT * FROM samples"):
  connection = database(root)
  try:
    return connection.execute(sql).fetchall()
  finally:
    connection.close()


def tree(root):
  return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def fill(redis_client):
  redis_client.set(f"{SENSOR}/current_temperature", json.dumps({"value": 19.5, "time": stamp(5)}))
  redis_client.set(f"{SENSOR}/target_temperature", json.dumps({"value": 21}))
  redis_client.set(f"{SENSOR}/target_heatingcooling_state", 1)
  redis_client.set(f"{SENSOR}/control_value", 0.4)
  redis_client.set(f"{SENSOR}/heating_cooling_state", 1)
  redis_client.set(f"{SENSOR}/boost", "false")
  redis_client.set("heating/shadow/zones/Bedrooms", json.dumps({"control_value": 0.35, "state": 1, "time": stamp(2)}))


def test_a_cycle_stores_the_legacy_and_shadow_values_of_each_zone(sampler, redis_client, root, clock):
  fill(redis_client)

  sampler.cycle()
  clock.advance(COMMIT_INTERVAL)
  sampler.cycle()

  row = stored(root, "SELECT temp, target, mode, ctl, hc, boost, sh_ctl, sh_state FROM samples ORDER BY ts LIMIT 1")
  assert row == [(19.5, 21.0, 1, 0.4, 1, 0, 0.35, 1)]


def test_a_stale_reading_is_stored_as_no_temperature(sampler, redis_client, root, clock):
  fill(redis_client)
  redis_client.set(f"{SENSOR}/current_temperature", json.dumps({"value": 19.5, "time": stamp(3 * 3600)}))

  sampler.cycle()
  clock.advance(COMMIT_INTERVAL)
  sampler.cycle()

  assert stored(root, "SELECT temp, ctl FROM samples ORDER BY ts LIMIT 1") == [(None, 0.4)]


def test_a_shadow_decision_that_stopped_updating_is_stored_as_none(sampler, redis_client, root, clock):
  fill(redis_client)
  redis_client.set("heating/shadow/zones/Bedrooms", json.dumps({"control_value": 0.35, "state": 1, "time": stamp(600)}))

  sampler.cycle()
  clock.advance(COMMIT_INTERVAL)
  sampler.cycle()

  assert stored(root, "SELECT ctl, sh_ctl, sh_state FROM samples ORDER BY ts LIMIT 1") == [(0.4, None, None)]


def test_missing_keys_give_a_row_of_nulls_not_a_crash(sampler, root, clock):
  sampler.cycle()
  clock.advance(COMMIT_INTERVAL)
  sampler.cycle()

  assert stored(root, "SELECT temp, ctl, sh_ctl FROM samples ORDER BY ts LIMIT 1") == [(None, None, None)]


def test_nothing_is_written_while_the_path_is_not_a_mount_point(sampler, redis_client, root, clock, mounted):
  fill(redis_client)
  mounted["value"] = False
  before = tree(root)

  for _ in range(3):
    sampler.cycle()
    clock.advance(COMMIT_INTERVAL)

  assert tree(root) == before
  assert sampler.history is None


def test_a_missing_mount_point_directory_is_not_created(redis_client, tmp_path, clock):
  missing = tmp_path / "heating_history"
  sampler = Sampler(redis_client, ZONES, root=str(missing), clock=clock)

  sampler.cycle()

  assert not missing.exists()


def test_the_real_mount_check_refuses_an_ordinary_directory(redis_client, root, clock):
  sampler = Sampler(redis_client, ZONES, root=str(root), clock=clock)
  before = tree(root)

  sampler.cycle()

  assert tree(root) == before


def test_a_missing_data_folder_is_not_created(redis_client, tmp_path, clock):
  sampler = Sampler(redis_client, ZONES, root=str(tmp_path), is_mounted=lambda path: True, clock=clock)

  sampler.cycle()

  assert tree(tmp_path) == []


def test_the_sampler_recovers_when_the_card_comes_back(sampler, redis_client, root, clock, mounted):
  fill(redis_client)
  mounted["value"] = False
  sampler.cycle()
  mounted["value"] = True
  clock.advance(SAMPLE_INTERVAL)

  sampler.cycle()
  clock.advance(COMMIT_INTERVAL)
  sampler.cycle()

  assert len(stored(root)) >= 1


def test_removing_the_card_stops_writes_and_closes_the_database(sampler, redis_client, root, clock, mounted):
  fill(redis_client)
  sampler.cycle()
  mounted["value"] = False
  clock.advance(SAMPLE_INTERVAL)

  sampler.cycle()

  assert sampler.history is None
  assert len(stored(root)) == 1


def test_samples_are_committed_about_once_a_minute(sampler, redis_client, root, clock):
  fill(redis_client)

  for _ in range(5):
    clock.advance(SAMPLE_INTERVAL)
    sampler.cycle()
  assert stored(root) == []

  for _ in range(2):
    clock.advance(SAMPLE_INTERVAL)
    sampler.cycle()
  assert len(stored(root)) == 7


def test_closing_commits_what_is_pending(sampler, redis_client, root, clock):
  fill(redis_client)
  sampler.cycle()
  assert stored(root) == []

  sampler.release()

  assert len(stored(root)) == 1


def test_a_redis_failure_skips_the_sample_and_warns_once(sampler, root, clock, caplog, monkeypatch):
  def broken(key):
    raise RedisConnectionError("down")

  monkeypatch.setattr(sampler.redis, "get", broken)

  for _ in range(3):
    clock.advance(SAMPLE_INTERVAL)
    sampler.cycle()

  assert [record.getMessage() for record in caplog.records if "redis failed" in record.getMessage()] == [
    "history skipped a sample, redis failed: down"]
  assert stored(root) == []


def test_a_database_error_reopens_it_on_the_next_cycle(sampler, redis_client, root, clock, monkeypatch):
  fill(redis_client)
  sampler.cycle()

  def failing(*args, **kwargs):
    raise sqlite3.OperationalError("disk I/O error")

  monkeypatch.setattr(sampler.history, "add", failing)
  clock.advance(SAMPLE_INTERVAL)
  sampler.cycle()
  assert sampler.history is None

  clock.advance(SAMPLE_INTERVAL)
  sampler.cycle()
  assert sampler.history is not None


def test_windows_are_built_from_the_samples_when_committing(sampler, redis_client, root, clock):
  fill(redis_client)
  clock.value = 1_800_000_000.0 - (1_800_000_000 % 600) + 5

  for _ in range(66):
    sampler.cycle()
    clock.advance(SAMPLE_INTERVAL)

  assert stored(root, "SELECT n FROM windows") == [(60,)]


def test_the_thread_samples_and_stops_cleanly(redis_client, root, mounted):
  fill(redis_client)
  sampler = Sampler(redis_client, ZONES, root=str(root), is_mounted=lambda path: True, interval=0.01)

  sampler.start()
  sampler.stop()

  assert not sampler.thread.is_alive()
  assert len(stored(root)) >= 1


def test_nothing_is_written_outside_the_data_folder(sampler, redis_client, root, clock):
  fill(redis_client)
  sampler.cycle()
  clock.advance(COMMIT_INTERVAL)
  sampler.cycle()
  sampler.release()

  assert {path.split("/")[0] for path in tree(root)} == {DATA_FOLDER}
