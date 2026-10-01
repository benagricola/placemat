"""The board edge judges copper and the rest of a part differently, as KiCad does: pads and copper
stay the keep-in (copper to edge clearance) inside the edge, a courtyard or body only inside the edge
itself. Pure: synthetic boards."""
import math

import pytest

from placemat.board_geometry import Footprint
from placemat.layout import Board
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.values import Box, Cell, Disc, Face, Location, Near, Part
from tests.fixtures import board_geometry, footprint, pad

CENTRE = 26.5           # a 53 mm disc: rim radius 26.5, keep-in 0.4 -> copper to 26.1


def _reach(mid, a0, a1):
    r = 0.0
    for a in (a0, a1):
        cx, cy = mid * math.cos(math.radians(a)), mid * math.sin(math.radians(a))
        r = max(r, max(math.hypot(cx + sx * 0.3, cy + sy * 0.3) for sx in (-1, 1) for sy in (-1, 1)))
    return r


def _sector(copper_reach, courtyard_reach, a0=190.0, a1=260.0, cell="ring"):
    """A member drawn as an arc sector about the board's centre: its courtyard polygon a band out to
    `courtyard_reach`, a pad at each end whose far corner reaches `copper_reach`."""
    lo, hi = 5.0, 40.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        lo, hi = (mid, hi) if _reach(mid, a0, a1) < copper_reach else (lo, mid)
    n = 16
    angles = [math.radians(a0 + (a1 - a0) * k / n) for k in range(n + 1)]
    r_in = mid - 1.5
    outer = [(CENTRE + courtyard_reach * math.cos(a), CENTRE + courtyard_reach * math.sin(a)) for a in angles]
    inner = [(CENTRE + r_in * math.cos(a), CENTRE + r_in * math.sin(a)) for a in reversed(angles)]
    poly = tuple(outer + inner)
    ends = [(CENTRE + mid * math.cos(math.radians(a)), CENTRE + mid * math.sin(math.radians(a))) for a in (a0, a1)]
    pads = tuple(pad("A1", "ring.a", k + 1, "N%d" % k, x, y, 0.6, 0.6) for k, (x, y) in enumerate(ends))
    box = Box.of_points(poly)
    return Footprint("A1", "ring.a", cell, "A1", Location(box.center.x, box.center.y), 0.0, Face.FRONT, box,
                     box, Box.union([p.box for p in pads]), pads, courtyard_poly=poly)


def _edge_findings(plan):
    return [f for f in plan.findings if "keep-in" in str(f) or "board edge" in str(f) or "outside" in str(f)]


def _board(fp):
    b = Board(board_geometry([fp], cells=["ring"], width=80, height=80), edge_margin=0.4, keep_going=True)
    b.disc(53.0)
    return b


def test_a_cell_whose_copper_is_at_the_keep_in_and_courtyard_nearer_the_edge_is_placed():
    fp = _sector(26.1 - 1e-4, 26.2)
    b = _board(fp)
    b.place(Cell("ring"), at=fp.body_box.center)
    plan = b.resolve()
    assert not _edge_findings(plan), plan.findings
    assert plan.placement("ring") is not None


def test_a_cell_whose_courtyard_crosses_the_edge_is_refused():
    fp = _sector(26.0, 26.6)
    b = _board(fp)
    b.place(Cell("ring"), at=fp.body_box.center)
    assert _edge_findings(b.resolve())


def test_a_cell_whose_copper_is_nearer_the_edge_than_the_keep_in_is_refused():
    fp = _sector(26.2, 26.3)            # 0.3 mm from the edge, keep-in 0.4
    b = _board(fp)
    b.place(Cell("ring"), at=fp.body_box.center)
    assert _edge_findings(b.resolve())


@pytest.mark.parametrize("native", [False, True])
def test_a_scan_puts_a_part_nearer_the_edge_by_its_courtyard_margin(native, monkeypatch):
    from placemat import geometry, placer
    if native and geometry._native is None:
        pytest.skip("no native module")
    monkeypatch.setattr(placer, "NATIVE_SWEEP", native)
    # a part whose courtyard reaches 0.25 past its body box on every side: against the west edge its
    # pads stand at the keep-in (0.4), its body 0.1 and its courtyard 0.05 from the edge
    fp = footprint("P1", 8, 10, w=4, h=2, inst="p1", excess=0.25)
    b = Board(board_geometry([fp], width=20, height=20), edge_margin=0.4, keep_going=True)
    b.place(Part("p1"), at=Near(Location(1.0, 10), radius=3.0, step=0.05, rotations=(0,)))
    plan = b.resolve()
    assert not _edge_findings(plan), plan.findings
    placed = plan.placement("p1")
    pads_left = placed.location.x - 2.0 + 0.1       # the west pad's left edge (pad 1 centred 0.6 in, 1.0 wide)
    assert pads_left == pytest.approx(0.4, abs=0.06)


def _scans(monkeypatch, make, at):
    """The scans a placement runs, once pure Python and once natively: (chosen, tried, rejected, reasons)
    of each, and the plan's placement."""
    from placemat import geometry, placer
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
        b, item, key = make()
        b.place(item, at=at)
        plan = b.resolve()
        runs[on] = ([(r.chosen, r.tried, dict(r.rejected), dict(r.reasons)) for r in seen], plan.placement(key))
    return runs


@pytest.mark.parametrize("excess", [0.1, 0.9])
@pytest.mark.parametrize("shape", ["disc", "rect"])
def test_a_scan_of_a_part_is_the_same_native_and_python(monkeypatch, shape, excess):
    # a courtyard 0.9 past the body is the edge's limit, 0.1 the copper's
    def make():
        fp = footprint("P1", 8, 10, w=4, h=2, inst="p1", excess=excess)
        b = Board(board_geometry([fp], width=20, height=20), edge_margin=0.4, keep_going=True)
        if shape == "disc":
            b.disc(20.0)
        return b, Part("p1"), "p1"
    runs = _scans(monkeypatch, make, Near(Location(1.0, 10), radius=4.0, step=0.1, rotations=(0, 45, 90)))
    assert runs[True] == runs[False]
    assert runs[True][1] is not None


def test_a_scan_of_a_cell_of_arc_members_is_the_same_native_and_python(monkeypatch):
    fp = _sector(25.9, 26.3)

    def make():
        b = _board(fp)
        return b, Cell("ring"), "ring"
    runs = _scans(monkeypatch, make, Near(fp.body_box.center, radius=1.0, step=0.5, rotations=(0, 90)))
    assert runs[True] == runs[False]


@pytest.mark.parametrize("shape", ["rect", "outline"])
@pytest.mark.parametrize("native", [None, False, True])         # None: a decided place, not a scan
def test_a_courtyard_crossing_the_edge_is_refused_with_its_copper_clear_of_the_keep_in(monkeypatch, shape, native):
    from placemat import geometry, placer
    if native and geometry._native is None:
        pytest.skip("no native module")
    monkeypatch.setattr(placer, "NATIVE_SWEEP", bool(native))

    def run(x):
        # a part whose courtyard stands 0.5 outside its body: its pads 1.9 inside the body's west side
        fp = footprint("P1", 10, 10, w=4, h=2, inst="p1", excess=0.5)
        b = Board(board_geometry([fp], width=20, height=20), edge_margin=0.4, keep_going=True)
        if shape == "outline":
            b.outline([(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)])
        b.place(Part("p1"), at=Location(x, 10) if native is None else Near(Location(x, 10), radius=0.0, rotations=(0,)))
        plan = b.resolve()
        at = plan.placement("p1")
        return _edge_findings(plan), at and at.location.x
    findings, at = run(2.4)           # pads at 0.5, courtyard at -0.1
    assert findings if native is None else at is None
    assert run(2.6) == ([], 2.6)
