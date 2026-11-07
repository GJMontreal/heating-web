import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
FILES = sorted(path for path in WEB.iterdir() if path.suffix in {".html", ".js", ".css"})
MARKUP_SINKS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function")


def test_the_web_folder_has_pages_to_check():
  assert {path.name for path in FILES} >= {"index.html", "style.css", "main.js"}


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_no_file_reaches_outside_the_device(path):
  text = path.read_text().replace("http://www.w3.org/2000/svg", "")

  assert not re.search(r"https?://|//cdn\.|@import", text)


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_no_file_writes_markup_from_data(path):
  text = path.read_text()

  assert not [sink for sink in MARKUP_SINKS if sink in text]


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.name)
def test_requests_are_get_only(path):
  methods = re.findall(r"method:\s*\"(\w+)\"", path.read_text())

  assert set(methods) <= {"GET"}
