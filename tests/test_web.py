import pytest
from fastapi.testclient import TestClient

from heating_web.app import create_app
from heating_web.zones import Zone

OWN_VERSION = {"version": "0.1.0", "commit": "abc1234", "time": "2025-11-07T12:00:00Z"}


@pytest.fixture
def client(redis_client):
  zones = [Zone("Bedrooms", "/home/sensors/a", "hydronic")]
  app = create_app(zones, redis_client, OWN_VERSION, unit_state=lambda name: "inactive")
  return TestClient(app)


def test_the_root_serves_the_page(client):
  response = client.get("/")

  assert response.status_code == 200
  assert response.headers["content-type"].startswith("text/html")
  assert "<title>Heating</title>" in response.text


def test_the_api_routes_are_unaffected_by_the_page(client):
  response = client.get("/api/services")

  assert response.status_code == 200
  assert response.headers["content-type"] == "application/json"
  assert [entry["name"] for entry in response.json()][0] == "boiler_relay"


def test_an_unknown_path_is_a_404(client):
  assert client.get("/nothing-here").status_code == 404
  assert client.get("/api/nothing-here").status_code == 404


def test_the_page_accepts_only_get(client):
  assert client.post("/").status_code == 405
