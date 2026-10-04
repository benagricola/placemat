"""A routed real board (fixtures/fairing/routed: a whole board after its route, KiCad's DRC clean on copper), read
as placemat reads it: its current paths, its stamped cells' labels and the gaps of its copper."""
import dataclasses
import math
from pathlib import Path

import pytest

from tests.conftest import needs_kicad

pytestmark = needs_kicad

BOARD = Path(__file__).resolve().parent.parent / "fixtures" / "fairing" / "routed" / "layout.kicad_pcb"
_read = {}


@pytest.fixture
def geometry():
    if not _read:
        from placemat.kicad.read import read_board
        _read["g"] = read_board(str(BOARD))
    return _read["g"]


def test_the_ground_net_is_judged_on_its_planes_not_a_sliver(geometry):
    """Through-hole carriers joined by inner planes on every layer: the
    widest route between them is the planes', not a sliver where two fills
    of the front layer meet (0.05 mm, one step, before)."""
    from placemat.checks import ZONE_STEP, current_paths
    v = {x.subject: x for x in current_paths(geometry)}["GND"]
    assert v.value > 1.0, v.note
    assert "one %g mm step or less" % ZONE_STEP not in v.note, v.note


def test_no_copper_finding_is_a_few_micrometres_short_of_its_rule(geometry):
    """Every straight track and every via, judged as a planned one against
    the rest of the board's copper: KiCad passes them all at their rules, so
    none reads short of its rule by the micrometres a polygon's round ends
    or a pour's mitred corners stand outside the copper."""
    from placemat.copper import Track, Via
    from placemat.layout import _shape_of
    from placemat.occupancy import Occupancy
    from placemat.values import Location
    occ = Occupancy(geometry, edge_margin=0.0)
    ops = []
    for c in geometry.copper:
        if c.kind == "via" and c.anchors:
            ops.append(Via(c.net, Location(*c.anchors[0]), c.drill_mm, c.width_mm))
        elif c.kind == "track" and len(c.anchors) == 2:
            (ax, ay), (bx, by) = c.anchors
            if not c.length_mm or abs(c.length_mm - math.hypot(bx - ax, by - ay)) < 1e-6:
                ops.append(Track(c.net, next(iter(c.layers)), c.width_mm, Location(ax, ay), Location(bx, by)))
    assert len(ops) > 1000
    short = [(op, f.facts) for op in ops for f in occ.copper_conflicts(_shape_of(op), check=True)
             if 0 < f.facts["need_mm"] - f.facts["gap_mm"] < 0.005]
    assert short == [], short[:5]
