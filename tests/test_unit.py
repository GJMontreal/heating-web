from pathlib import Path

UNIT = Path(__file__).resolve().parent.parent / "deploy" / "heating_web.service.template"
TAKEN = {6379, 1883, 8000, 8080, 8581}


def exec_start():
  line = next(line for line in UNIT.read_text().splitlines() if line.startswith("ExecStart="))
  return line.split()


def test_the_unit_listens_on_a_port_nothing_else_uses_on_the_device():
  words = exec_start()
  port = int(words[words.index("--port") + 1])

  assert port == 8090
  assert port not in TAKEN


def test_the_unit_does_not_depend_on_or_conflict_with_any_boiler_relay_unit():
  text = UNIT.read_text()

  assert "Conflicts=" not in text
  assert "Requires=" not in text
  assert "boiler_relay" not in text
