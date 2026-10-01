"""A part's `Pm.KeepOut` on three real switching-regulator modules (fixtures/fairing/keep_out: each one's layout script,
generated board and netlist), run end to end as `placemat run` does and judged by kicad-cli's DRC on the board it
writes. Each runs under both wordings of its capture: the switch node alone in `away=`, and the boot node named
too. The settings carry no `[place] conflict_gap`: the keep-out's distance is enough by itself."""
import re

import pytest

from tests import real_modules as rm
from tests.conftest import needs_kicad

pytestmark = needs_kicad

DISTANCE = {"usb5v": 1.28, "logicsupply": 1.22, "usbconverter": 1.26}
# the wording that names the boot node as well, as the generated netlist of each module has it
BOOT_NAMED = {
    "usb5v": "1.28mm pads=FB_5V away=SW_5V,BST_5V; datasheet fig. 12-2: SW and boot copper leave the package beside FB, at its own pad gap (1.28 mm)",
    "logicsupply": "1.22mm pads=FB_3V3 away=SW_3V3,BST_3V3; datasheet fig. 12-2: SW and boot copper leave the package beside FB, at its own pad gap (1.22 mm)",
    "usbconverter": "1.26mm pads=COMP_BB away=SW1,SW2,BOOT1,BOOT2; datasheet fig. 10-1: SW and boot copper leave the package beside COMP, at its own pad gap (1.26 mm)",
}
WORDINGS = {"switch node only": rm.SWITCH_ONLY, "boot node named": BOOT_NAMED}
_runs = {}


def _run(tmp_path_factory, module, wording):
    key = (module, wording)
    if key not in _runs:
        tmp = tmp_path_factory.mktemp("%s-%s" % (module, wording.replace(" ", "-")))
        result, drc, pcb = rm.run(tmp, module, WORDINGS[wording][module])
        _runs[key] = (result, drc, pcb)
    return _runs[key]


def _words(module):
    return [(m, w) for m in rm.MODULES for w in WORDINGS]


@pytest.fixture(params=_words(None), ids=lambda p: "%s/%s" % p)
def run(request, tmp_path_factory):
    module, wording = request.param
    return module, _run(tmp_path_factory, module, wording)


def test_the_run_starts_with_no_conflict_gap_of_its_own(run):
    module, (result, _, _) = run
    import tomllib
    assert "conflict_gap" not in tomllib.loads((rm.FIXTURES / "placemat.toml").read_text())["place"]
    assert result.status == "ok", result.record.failure


def test_kicad_finds_no_short_and_no_clearance_violation_on_the_written_board(run):
    module, (result, drc, pcb) = run
    bad = rm.violations(drc, "shorting_items", "clearance")
    assert not bad, bad


def test_the_plan_reports_no_copper_through_another_nets_copper(run):
    module, (result, _, _) = run
    through = [f for f in result.record.findings if re.search(r"is 0\.00 mm from|cross on .* neither may bridge|crosses FIXED", f)]
    assert not through, through


def test_a_part_s_own_pad_escapes_are_not_findings_of_its_keep_out(run):
    module, (result, drc, _) = run
    held = [f for f in result.record.findings if "keep-out" in f]
    assert not held, held
    ours = [v for v in rm.violations(drc, "clearance") if "keep-out" in v]
    assert not ours, ours


SWITCH_NODES = {"usb5v": ("SW_5V",), "logicsupply": ("SW_3V3",), "usbconverter": ("SW1", "SW2")}


def test_the_keep_out_check_judges_a_part_by_its_own_distance(run):
    module, (result, _, _) = run
    judged = [v for v in result.record.verdicts if v["check"] == "keep-out"]
    held = [v for v in judged if v["subject"] in SWITCH_NODES[module]]
    assert held, [v["subject"] for v in judged]
    assert all(v["limit"] == pytest.approx(DISTANCE[module]) and "Pm.KeepOut" in v["note"] for v in held), \
        [(v["subject"], v["value"], v["limit"]) for v in held]
    assert all(v["ok"] is not False for v in judged), [(v["subject"], v["value"], v["limit"], v["note"]) for v in judged]
    named = [v for v in judged if "Pm.KeepOut" in v["note"]]
    assert all(v["limit"] <= DISTANCE[module] + 1e-9 for v in named)
