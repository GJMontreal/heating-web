import fakeredis
import pytest


@pytest.fixture
def redis_server():
  return fakeredis.FakeServer()


@pytest.fixture
def redis_client(redis_server):
  return fakeredis.FakeRedis(server=redis_server)
