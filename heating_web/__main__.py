import logging
import sys
from argparse import ArgumentParser

import uvicorn
from redis import Redis
from redis.exceptions import RedisError

from heating_web.app import create_app
from heating_web.version import build_entry, describe, publish_version
from heating_web.zones import DEFAULT_ZONES, ZonesError, load_zones

log = logging.getLogger("heating_web")


def parse_arguments(argv=None):
    parser = ArgumentParser(description="Read-only web API for the heating system")
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on")
    parser.add_argument("--port", type=int, default=8080, help="port to listen on")
    parser.add_argument("--zones", default=DEFAULT_ZONES, help="the control service's system_config.json")
    parser.add_argument("--redis-host", default="localhost")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--version", action="version", version=describe())
    return parser.parse_args(argv)


def announce(redis, entry):
    try:
        publish_version(redis, entry)
    except RedisError as error:
        log.warning("could not publish the version: %s", error)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_arguments(argv)

    try:
        zones = load_zones(args.zones)
    except ZonesError as error:
        log.error("invalid zones file: %s", error)
        return 2

    redis = Redis(host=args.redis_host, port=args.redis_port, db=0)
    entry = build_entry()
    announce(redis, entry)
    uvicorn.run(create_app(zones, redis, entry), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
