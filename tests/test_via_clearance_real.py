"""A real fragment (fixtures/fairing/via_clearance: its layout script, generated board and the core's settings) run end
to end, judged by kicad-cli's DRC on the board it writes. A track leg planned under a 0.10 mm rule beside a via stood
0.0986 mm from it, and no finding may read a shortfall as equal to the limit."""
import json
import re

import pytest

from tests import real_modules as rm
from tests.conftest import needs_kicad

pytestmark = needs_kicad

_run = {}


@pytest.fixture
def run(tmp_path_factory):
    if not _run:
        _run["r"] = rm.run(tmp_path_factory.mktemp("usbtcpc"), "usbtcpc")
    return _run["r"]


def test_kicad_finds_no_clearance_violation(run):
    result, drc, _ = run
    assert result.status == "ok", result.record.failure
    assert rm.violations(drc, "clearance", "hole_clearance", "shorting_items") == []


def test_no_finding_reads_a_shortfall_as_the_limit(run):
    """A finding exists because the gap is under the limit, so its figure must read under it."""
    result, _, _ = run
    said = json.loads((result.run_dir / "run.json").read_text())["findings"]
    assert said, "the module reports findings (the board edge, the part libraries)"
    for text in map(str, said):
        for m in re.finditer(r"([0-9.]+) mm from [^()]*\((?:hole-to-hole )?needs ([0-9.]+)", text):
            assert float(m.group(1)) < float(m.group(2)), text
