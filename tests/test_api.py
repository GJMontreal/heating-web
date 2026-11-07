import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from heating_web.app import SERVICES, create_app
from heating_web.zones import Zone

SENSOR = "/home/sensors/a"
ZONES = [Zone("Bedrooms", SENSOR, "hydronic")]


def timestamp(age=0):
  moment = datetime.now(timezone.utc) - timedelta(seconds=age)
  return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def states():
  return {}


@pytest.fixture
def client(redis_client, states):
  app = create_app(ZONES, redis_client, unit_state=lambda name: states.get(name, "inactive"))
  return TestClient(app)


def zone(client):
  response = client.get("/api/live")
  assert response.status_code == 200
  return response.json()[0]


def test_live_is_empty_of_readings_before_anything_is_written(client):
  data = zone(client)

  assert data["name"] == "Bedrooms"
  assert data["current_temperature"] is None
  assert data["sensor_stale"] is True
  assert data["control_value"] is None
  assert data["active"] is None and data["shadow"] is None


def test_live_returns_the_homebridge_keys_and_the_sensor_age(client, redis_client):
  redis_client.set(f"{SENSOR}/current_temperature", json.dumps({"value": 19.5, "time": timestamp(30)}))
  redis_client.set(f"{SENSOR}/target_temperature", json.dumps({"value": 21}))
  redis_client.set(f"{SENSOR}/target_heatingcooling_state", 1)
  redis_client.set(f"{SENSOR}/control_value", 0.4)
  redis_client.set(f"{SENSOR}/heating_cooling_state", 1)
  redis_client.set(f"{SENSOR}/boost", "false")

  data = zone(client)

  assert data["current_temperature"]["value"] == 19.5
  assert 29 <= data["current_temperature"]["age_seconds"] <= 40
  assert data["sensor_stale"] is False
  assert data["target_temperature"] == 21
  assert data["target_state"] == 1
  assert data["control_value"] == 0.4
  assert data["heating_cooling_state"] == 1
  assert data["boost"] is False


def test_a_reading_older_than_two_hours_is_stale(client, redis_client):
  redis_client.set(f"{SENSOR}/current_temperature", json.dumps({"value": 19.5, "time": timestamp(2 * 3600 + 60)}))

  assert zone(client)["sensor_stale"] is True


def test_live_includes_the_published_active_and_shadow_state(client, redis_client):
  redis_client.set("heating/active/zones/Bedrooms", json.dumps({"control_value": 0.5, "state": 1, "time": timestamp()}))
  redis_client.set("heating/shadow/zones/Bedrooms", json.dumps({"control_value": 0.4, "state": 0, "time": timestamp()}))

  data = zone(client)

  assert data["active"]["control_value"] == 0.5
  assert data["shadow"]["state"] == 0


def test_an_unreadable_target_state_is_null(client, redis_client):
  redis_client.set(f"{SENSOR}/target_heatingcooling_state", "heat")

  assert zone(client)["target_state"] is None


def test_services_lists_the_control_services_and_the_bridge(client, states):
  states["mqtt_bridge"] = "active"
  states["boiler_relay"] = "failed"

  response = client.get("/api/services")

  assert [item["name"] for item in response.json()] == list(SERVICES)
  assert {item["name"]: item["state"] for item in response.json()}["mqtt_bridge"] == "active"
  assert {item["name"]: item["state"] for item in response.json()}["boiler_relay"] == "failed"


def test_the_api_has_no_write_routes(client):
  methods = {method for route in client.app.routes for method in getattr(route, "methods", set())}

  assert methods <= {"GET", "HEAD", "OPTIONS"}
