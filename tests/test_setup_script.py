import os
import subprocess
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parent.parent / "deploy" / "setup_python.sh.template"

STUBS = {
  "nice": 'echo "nice $1 $2" >> "$LOG"\nshift 2\nexec "$@"\n',
  "ionice": 'echo "ionice $1" >> "$LOG"\nshift\nexec "$@"\n',
  "python3": (
    'echo "python3 $*" >> "$LOG"\n'
    'case "$*" in\n'
    '  *venv*) [ -n "$FAIL_VENV" ] && exit 1; mkdir -p .venv/bin; : > .venv/bin/activate ;;\n'
    '  *pip*) [ -n "$FAIL_PIP" ] && exit 1 ;;\n'
    'esac\n'
    'exit 0\n'
  ),
}


@pytest.fixture
def run(tmp_path):
  install = tmp_path / "install"
  install.mkdir()
  bin_dir = tmp_path / "bin"
  bin_dir.mkdir()
  for name, body in STUBS.items():
    stub = bin_dir / name
    stub.write_text("#!/bin/sh\n" + body)
    stub.chmod(0o755)
  script = tmp_path / "setup_python.sh"
  script.write_text(TEMPLATE.read_text().replace("/var/lib/<service_name>", str(install)))
  log = tmp_path / "log"

  def go(**env):
    result = subprocess.run(
      ["/bin/sh", str(script)],
      env={"PATH": "{}:/usr/bin:/bin".format(bin_dir), "LOG": str(log), **env},
      stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=30)
    lines = log.read_text().splitlines() if log.exists() else []
    return result, lines

  return go


def test_the_venv_and_the_install_both_run_at_low_priority(run):
  result, lines = run()

  assert result.returncode == 0, result.stderr
  assert lines == [
    "nice -n 19",
    "ionice -c3",
    "python3 -m venv ./.venv",
    "nice -n 19",
    "ionice -c3",
    "python3 -m pip install -r requirements.txt",
  ]


def test_a_failing_pip_fails_the_script(run):
  result, lines = run(FAIL_PIP="1")

  assert result.returncode != 0
  assert lines[-1] == "python3 -m pip install -r requirements.txt"


def test_a_failing_venv_stops_before_pip(run):
  result, lines = run(FAIL_VENV="1")

  assert result.returncode != 0
  assert not any("pip" in line for line in lines)
