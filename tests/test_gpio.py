import ast
import builtins
import re
from pathlib import Path

import pytest

from heating_web import gpio
from heating_web.gpio import PIN_NUMBERS, SysfsReader

IN_USE = {"P8_7": 66, "P8_8": 67, "P8_9": 69, "P8_10": 68, "P8_11": 45, "P8_12": 44, "P8_14": 26,
          "P8_15": 47, "P8_16": 46, "P8_17": 27, "P8_18": 65, "P8_27": 86, "P8_28": 88}
SOURCE = Path(gpio.__file__)
FORBIDDEN_CALLS = {"write", "writelines", "write_text", "write_bytes", "truncate", "unlink", "remove", "rmdir",
                   "mkdir", "makedirs", "rename", "replace", "touch", "chmod", "symlink_to", "system", "Popen"}


def make_pin(root, pin, text):
  directory = root / f"gpio{PIN_NUMBERS[pin]}"
  directory.mkdir(parents=True, exist_ok=True)
  (directory / "value").write_text(text)


def snapshot(root):
  return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
          for path in sorted(root.rglob("*")) if path.is_file()}


def test_the_pins_in_use_have_the_numbers_measured_on_the_device():
  assert {pin: PIN_NUMBERS[pin] for pin in IN_USE} == IN_USE


def test_every_table_entry_is_a_header_pin_and_no_number_repeats():
  assert all(re.fullmatch(r"P[89]_\d{1,2}", pin) for pin in PIN_NUMBERS)
  assert len(set(PIN_NUMBERS.values())) == len(PIN_NUMBERS)


def test_a_level_is_read_from_the_value_file(tmp_path):
  make_pin(tmp_path, "P8_8", "1\n")
  make_pin(tmp_path, "P8_7", "0\n")
  reader = SysfsReader(str(tmp_path))

  assert reader.level("P8_8") == 1
  assert reader.level("P8_7") == 0


def test_a_pin_that_is_not_exported_has_no_level(tmp_path):
  assert SysfsReader(str(tmp_path)).level("P8_8") is None


def test_a_pin_missing_from_the_table_has_no_level(tmp_path):
  assert SysfsReader(str(tmp_path)).level("P8_99") is None


@pytest.mark.parametrize("text", ["", "2\n", "high\n", "10\n"])
def test_unexpected_file_content_has_no_level(tmp_path, text):
  make_pin(tmp_path, "P8_8", text)

  assert SysfsReader(str(tmp_path)).level("P8_8") is None


def test_an_unreadable_value_has_no_level(tmp_path):
  (tmp_path / f"gpio{PIN_NUMBERS['P8_8']}" / "value").mkdir(parents=True)

  assert SysfsReader(str(tmp_path)).level("P8_8") is None


def test_reading_opens_every_file_read_only_and_changes_nothing(tmp_path, monkeypatch):
  make_pin(tmp_path, "P8_8", "1\n")
  make_pin(tmp_path, "P8_7", "0\n")
  before = snapshot(tmp_path)
  modes = []
  real_open = builtins.open

  def recording_open(file, mode="r", *args, **kwargs):
    modes.append(mode)
    return real_open(file, mode, *args, **kwargs)

  monkeypatch.setattr(gpio, "open", recording_open, raising=False)
  reader = SysfsReader(str(tmp_path))

  for pin in ("P8_8", "P8_7", "P8_9"):
    reader.level(pin)

  assert modes == ["r", "r", "r"]
  assert snapshot(tmp_path) == before
  assert sorted(path.name for path in tmp_path.iterdir()) == sorted(f"gpio{PIN_NUMBERS[pin]}" for pin in ("P8_8", "P8_7"))


def literals(tree):
  kinds = tuple(kind for kind in (getattr(ast, "Constant", None), getattr(ast, "Str", None)) if kind)
  return [ast.literal_eval(node) for node in ast.walk(tree) if isinstance(node, kinds)]


def test_the_sysfs_code_has_no_write_call_and_never_names_export():
  tree = ast.parse(SOURCE.read_text())
  calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
  opens = [call for call in calls if isinstance(call.func, ast.Name) and call.func.id == "open"]
  attributes = {call.func.attr for call in calls if isinstance(call.func, ast.Attribute)}
  names = {call.func.id for call in calls if isinstance(call.func, ast.Name)}
  strings = {value for value in literals(tree) if isinstance(value, str)}
  imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
  imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

  assert opens
  assert all(len(call.args) == 2 and ast.literal_eval(call.args[1]) == "r" and not call.keywords for call in opens)
  assert not (attributes | names) & FORBIDDEN_CALLS
  assert not {"os", "shutil", "subprocess", "pathlib"} & imports
  assert not [text for text in strings if "export" in text]
