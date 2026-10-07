"""vulture finds no unused code in the package beyond tools/release/vulture_allow.py, each entry there with a reason."""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_no_unused_code():
    pytest.importorskip("vulture")
    r = subprocess.run([sys.executable, "-m", "vulture", "src/placemat", "tools/release/vulture_allow.py",
                        "--min-confidence", "80"], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert r.stdout.strip() == "", r.stdout
