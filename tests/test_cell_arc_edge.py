"""A cell of arc-shaped members along a round rim: the keep-in is judged by what
each member is, not by the box round it. Pure: synthetic boards."""
import math

import pytest

from placemat.board_geometry import Footprint
from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.values import Box, Cell, Face, Location
from tests.fixtures import board_geometry, footprint, pad

CENTRE = 20.0           # a 40 mm disc: rim radius 20, keep-in 0.4 -> 19.6


def _arc(ref, inst, a0, a1, r_in, r_out, cell="ring"):
    """A part shaped as a band of an annulus about (CENTRE, CENTRE), from bearing a0 to a1 degrees,
    with a pad at each end: its courtyard polygon is the band, its box the box round it."""
    n = 12
    angles = [math.radians(a0 + (a1 - a0) * k / n) for k in range(n + 1)]
    outer = [(CENTRE + r_out * math.cos(a), CENTRE + r_out * math.sin(a)) for a in angles]
    inner = [(CENTRE + r_in * math.cos(a), CENTRE + r_in * math.sin(a)) for a in reversed(angles)]
    poly = tuple(outer + inner)
    mid = (r_in + r_out) / 2.0
    ends = [(CENTRE + mid * math.cos(angles[i]), CENTRE + mid * math.sin(angles[i])) for i in (0, -1)]
    pads = tuple(pad(ref, inst, k + 1, "N%d" % k, x, y, 0.6, 0.6) for k, (x, y) in enumerate(ends))
    box = Box.of_points(poly)
    return Footprint(ref, inst, cell, ref, Location(box.center.x, box.center.y), 0.0, Face.FRONT, box,
                     box.inflate(0.0), box, pads, courtyard_poly=poly)


def _round_board(fps, cells=("ring",), disc=True):
    b = Board(board_geometry(fps, cells=list(cells), width=60, height=60), edge_margin=0.4, keep_going=True)
    b.outline(Circle(40.0)) if not disc else b.disc(40.0)
    return b


def _edge_findings(plan):
    return [f for f in plan.findings if "keep-in" in str(f) or "board edge" in str(f) or "outside" in str(f)]


def _members_along_the_rim(n=7, r=18.0):
    fps = []
    for k in range(n):
        a = math.radians(180 + 90 * k / (n - 1))
        fps.append(footprint("W%d" % k, CENTRE + r * math.cos(a), CENTRE + r * math.sin(a), w=2.0, h=1.0,
                             inst="ring.w%d" % k, nets=("A%d" % k, "B%d" % k), cell="ring"))
    return fps


@pytest.mark.parametrize("disc", [True, False])
def test_a_cell_of_members_along_the_rim_whose_box_crosses_the_keep_in_is_placed(disc):
    fps = _members_along_the_rim()
    geom = board_geometry(fps, cells=["ring"], width=60, height=60)
    box = geom.cells["ring"].box
    assert math.hypot(box.left - CENTRE, box.top - CENTRE) > 19.6        # its box's corner is past the keep-in
    b = _round_board(fps, disc=disc)
    b.place(Cell("ring"), at=box.center)
    assert not _edge_findings(b.resolve())


@pytest.mark.parametrize("disc", [True, False])
def test_a_cell_of_arc_shaped_members_whose_boxes_cross_the_keep_in_is_placed(disc):
    fps = [_arc("A1", "ring.a", 185, 265, 17.0, 19.0), _arc("A2", "ring.b", 275, 355, 17.0, 19.0)]
    for fp in fps:
        assert math.hypot(fp.body_box.left - CENTRE, fp.body_box.top - CENTRE) > 19.6 or \
            math.hypot(fp.body_box.right - CENTRE, fp.body_box.top - CENTRE) > 19.6
    b = _round_board(fps, disc=disc)
    geom_box = Box.union([fp.body_box for fp in fps])
    b.place(Cell("ring"), at=geom_box.center)
    assert not _edge_findings(b.resolve())


def test_a_cell_with_a_member_past_the_rim_is_still_refused():
    fps = [_arc("A1", "ring.a", 185, 265, 17.0, 19.9), _arc("A2", "ring.b", 275, 355, 17.0, 19.0)]
    b = _round_board(fps)
    b.place(Cell("ring"), at=Box.union([fp.body_box for fp in fps]).center)
    assert _edge_findings(b.resolve())


def test_a_searched_cell_of_members_along_the_rim_is_the_same_native_and_python(monkeypatch):
    """The scan judges the members' boxes natively as Python does: the same spot, tries and
    refusals, and the spot is one the cell's whole box would lose."""
    from placemat import geometry, placer
    from placemat.values import Near
    if geometry._native is None:
        pytest.skip("no native module")
    runs = {}
    base = placer.ScanResult
    for on in (False, True):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", on)
        seen = []

        class Recorded(base):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                seen.append(self)
        monkeypatch.setattr(placer, "ScanResult", Recorded)
        fps = _members_along_the_rim()
        b = _round_board(fps, disc=False)
        box = board_geometry(fps, cells=["ring"], width=60, height=60).cells["ring"].box
        b.place(Cell("ring"), at=Near(box.center, radius=1.0, step=0.5, rotations=(0,)))
        plan = b.resolve()
        runs[on] = ([(r.chosen, r.tried, dict(r.rejected), dict(r.reasons)) for r in seen], plan.placement("ring"))
    assert runs[True] == runs[False]
    assert runs[True][1] is not None and not _edge_findings(plan)
