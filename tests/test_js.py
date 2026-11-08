import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = sorted(str(path) for path in (Path(__file__).parent / "js").glob("*.test.mjs"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_javascript_tests_pass():
  result = subprocess.run(["node", "--test"] + JS_TESTS, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)

  assert result.returncode == 0, result.stdout
