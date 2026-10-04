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


def _ground(geometry):
    """The ground net's current-path verdict, judged once for the tests that read it."""
    if "gnd" not in _read:
        from placemat.checks import current_paths
        _read["gnd"] = {x.subject: x for x in current_paths(geometry)}["GND"]
    return _read["gnd"]


def test_the_ground_net_is_judged_on_its_planes_not_a_sliver(geometry):
    """Through-hole carriers joined by inner planes on every layer: the
    widest route between them is the planes', not a sliver where two fills
    of the front layer meet (0.05 mm, one step, before)."""
    from placemat.checks import ZONE_STEP
    v = _ground(geometry)
    assert v.value > 1.0, v.note
    assert "one %g mm step or less" % ZONE_STEP not in v.note, v.note


def test_the_ground_planes_carry_the_current_in_parallel(geometry):
    """The ground route's neck is on one inner plane between two vias, and
    the other inner plane joins the same two vias: the neck is judged by
    both planes' widths added (1.47 mm on one plane alone, before)."""
    v = _ground(geometry)
    on = {d["layer"]: d for d in v.facts["layers"]}
    assert {"In1.Cu", "In4.Cu"} <= set(on), v.facts["layers"]
    assert on["In1.Cu"]["width_mm"] > 1.0 and on["In4.Cu"]["width_mm"] > 1.0
    assert v.value == pytest.approx(sum(d["width_mm"] * d["scale"] for d in on.values()))
    assert v.value > on["In1.Cu"]["width_mm"] + 1.0


def test_a_cell_whose_label_lies_on_a_placed_part_is_refused_where_it_stands(geometry):
    """Each stamped cell with labels, judged where it landed against
    everything else: refused for its silk exactly when one of its labels'
    boxes lies over another part's mask opening on the cell's face."""
    from placemat.geometry import polys_overlap
    from placemat.occupancy import Occupancy
    from placemat.placement import Placement
    from placemat.settings import Settings
    from placemat.values import Face
    occ = Occupancy(geometry, edge_margin=0.0, settings=dataclasses.replace(Settings(), place_envelope="physical"))
    labelled = sorted({ra.cell for ra in geometry.rule_areas if ra.cell and ra.name.startswith("label ")})
    assert labelled
    refused = 0
    for name in labelled:
        cell = geometry.cell(name)
        mine = {fp.ref for fp in cell.members}
        on = [(ra.polygon, next(l.face for l in ra.layers)) for ra in geometry.rule_areas
              if ra.cell == name and ra.name.startswith("label ")]
        covers = any(face == mface and polys_overlap(poly, mask)
                     for fp in geometry.footprints if fp.ref not in mine
                     for mface, mask in fp.mask for poly, face in on)
        geom = occ._geometry(cell)
        why = occ.legal(cell, Placement(geom.reference.location, 0.0, Face.FRONT))     # where it stands
        if covers:
            refused += 1
            assert why is not None and "silk" in str(why), (name, why)
    assert refused, "the board has a cell whose label lies on another part"


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
