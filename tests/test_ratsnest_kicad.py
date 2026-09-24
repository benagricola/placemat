"""placemat's ratsnest against KiCad's own, on every benchmark module board
as it stands: the airwires kicad-cli's DRC reports as unconnected items.

KiCad's report gives each airwire's ends as its items' positions. For a pad
that is where the airwire ends; for a track or a via it is the item's own
position, not the end the airwire actually leaves from. So the comparison is
made on the boards whose airwires all end at pads, which is every board the
placement search works on. Equal-length airwires are tied, and KiCad breaks
a tie by its node set's order, which follows memory addresses: the crossing
count may differ by that (report.py's AIRWIRE_NOISE note)."""
import json
import math
import re
import sys
from pathlib import Path

import pytest

from tests.conftest import needs_kicad

pytestmark = [needs_kicad]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fixtures"))
import bench  # noqa: E402


def _pads_only(drc) -> bool:
    return all(i.get("description", "").startswith(("Pad ", "PTH pad ", "NPTH pad "))
               for u in drc.get("unconnected_items", []) for i in u.get("items", []))


@pytest.mark.parametrize("pcb", bench.boards(), ids=bench._name)
def test_the_airwires_are_kicads(pcb, tmp_path):
    from placemat.kicad.drc import run_drc
    from placemat.kicad.read import read_board
    from placemat.ratsnest import crossings, from_geometry
    from placemat.report import airwires_from_drc
    out = tmp_path / "drc.json"
    run_drc(pcb, out)
    drc = json.loads(out.read_text())
    if not _pads_only(drc):
        pytest.skip("an airwire ends at a track or via, whose reported position is not its end")
    theirs = airwires_from_drc(drc)
    edges = from_geometry(read_board(pcb)).edges()
    assert len(edges) == theirs["count"]
    assert sum(math.hypot(e.a.x - e.b.x, e.a.y - e.b.y) for e in edges) == pytest.approx(theirs["total_mm"], abs=0.01)
    ours = crossings(edges)[0]
    assert abs(ours - theirs["crossings"]) <= max(1, 0.01 * theirs["crossings"])
