import json
import logging
import os
import unicodedata
from threading import Lock

log = logging.getLogger(__name__)

DEFAULT_SITE_FILE = "/etc/heating/site.json"
DEFAULT_NAME = "Heating"
MAX_LENGTH = 60
KEY = "site_name"
FORBIDDEN_CATEGORIES = ("Cc", "Zl", "Zp")


def valid_name(value):
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name or len(name) > MAX_LENGTH:
        return None
    if any(unicodedata.category(character) in FORBIDDEN_CATEGORIES for character in name):
        return None
    return name


class SiteName:
    def __init__(self, path=DEFAULT_SITE_FILE, configured=None):
        self.path = path
        self.lock = Lock()
        self.signature = None
        self.from_file = None
        self.warned = set()
        self.from_config = None
        if configured is not None:
            self.from_config = valid_name(configured)
            if self.from_config is None:
                self.warn_once("config", "ignoring site_name in the control config: it is not a usable name")

    def warn_once(self, condition, message, *arguments):
        if condition not in self.warned:
            self.warned.add(condition)
            log.warning(message, *arguments)

    def read_file(self):
        try:
            signature = os.stat(self.path).st_mtime_ns
        except OSError:
            self.signature = None
            self.from_file = None
            self.warned.discard("file")
            return
        if signature == self.signature:
            return
        try:
            with open(self.path, "r") as file:
                data = json.load(file)
        except OSError:
            self.from_file = None
            self.warn_once("file", "ignoring %s: it cannot be read", self.path)
            return
        except ValueError:
            data = None
        self.signature = signature
        self.from_file = valid_name(data.get(KEY)) if isinstance(data, dict) else None
        if self.from_file is None:
            self.warn_once("file", "ignoring %s: it has no usable %s", self.path, KEY)
        else:
            self.warned.discard("file")

    def name(self):
        with self.lock:
            self.read_file()
            for value in (self.from_file, self.from_config):
                if value is not None:
                    return value
        return DEFAULT_NAME
