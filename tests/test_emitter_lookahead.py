"""A source placed before its limit partner is not left a spot with no room for the partner (and the
other way round): the search looks ahead to the unplaced counterpart's legal spots. Pure: synthetic boards."""
import dataclasses
import re


from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Face, Location, Near, PadRef, Part, Polar, Priority
from tests.fixtures import board_geometry, footprint

EMITS = "magnetic:3.2mT@13.5mm^3"
LIMIT = "magnetic:0.5mT"
REACH = 13.5 * (3.2 / 0.5) ** (1.0 / 3.0)       # 25.1 mm
R = 24.0                                         # the disc's radius: no spot 25.1 mm from its centre is left on it
CENTRE = Location(R, R)


def _fps():
    m1 = footprint("M1", 70, 10, w=4, h=4, inst="m1", nets=("A", "GND"), fields={"Pm.Emits": EMITS})
    u2 = footprint("U2", 70, 20, w=2, h=2, inst="u2", nets=("SIG", "GND"), fields={"Pm.Limit": LIMIT})
    return [m1, u2]


def _board(settings=None, fps=None, band=(0.0, 6.0)):
    fps = fps or _fps()
    b = Board(board_geometry(fps, width=80, height=80), edge_margin=0.4, keep_going=True,
              **({"settings": settings} if settings else {}))
    b.disc(2 * R)
    b.place(Part("m1"), at=Polar(band, None, about=CENTRE), priority=Priority.HIGH, step=1.0)
    b.place(Part("u2"), priority=Priority.HIGH, face=Face.EITHER, step=1.0)
    return b


def _gap(plan, a="m1", b="u2"):
    return plan.box(a).center.distance(plan.box(b).center)


def test_a_source_leaves_its_partner_a_spot_when_the_centre_would_not():
    plan = _board().resolve()
    assert plan.placement("m1") is not None and plan.placement("u2") is not None, plan.findings
    assert _gap(plan) >= REACH - 1e-6


def test_without_the_look_ahead_the_centre_leaves_the_partner_nothing():
    plan = _board(dataclasses.replace(Settings(), place_lookahead=False)).resolve()
    assert plan.placement("m1") is not None
    assert plan.placement("u2") is None
    assert plan.placement("m1") != _board().resolve().placement("m1")


def test_a_source_with_room_for_its_partner_is_placed_as_before():
    wide = Board(board_geometry(_fps(), width=80, height=80), edge_margin=0.4, keep_going=True)
    wide.disc(2 * 40.0)
    wide.place(Part("m1"), at=Polar((0.0, 6.0), None, about=Location(40, 40)), priority=Priority.HIGH, step=1.0)
    wide.place(Part("u2"), priority=Priority.HIGH, face=Face.EITHER, step=1.0)
    off = Board(board_geometry(_fps(), width=80, height=80), edge_margin=0.4, keep_going=True,
                settings=dataclasses.replace(Settings(), place_lookahead=False))
    off.disc(2 * 40.0)
    off.place(Part("m1"), at=Polar((0.0, 6.0), None, about=Location(40, 40)), priority=Priority.HIGH, step=1.0)
    off.place(Part("u2"), priority=Priority.HIGH, face=Face.EITHER, step=1.0)
    a, b = wide.resolve(), off.resolve()
    assert a.placement("m1") == b.placement("m1") and a.placement("u2") == b.placement("u2")


def _sensitive_first(settings=None):
    """The sensitive part is the larger, so it is placed first; a link to a part at the disc's centre
    pulls it there, and the source it leaves a spot for is searched wide."""
    m1 = footprint("M1", 70, 10, w=2, h=1, inst="m1", nets=("A", "GND"), fields={"Pm.Emits": EMITS})
    u2 = footprint("U2", 70, 20, w=2, h=3, inst="u2", nets=("SIG", "GND"), fields={"Pm.Limit": LIMIT})
    j1 = footprint("J1", 70, 30, w=1, h=1, inst="j1", nets=("SIG", "PWR"))
    b = Board(board_geometry([m1, u2, j1], width=80, height=80), edge_margin=0.4, keep_going=True,
              **({"settings": settings} if settings else {}))
    small = 23.0
    mid = Location(small, small)
    b.disc(2 * small)
    b.place(Part("j1"), at=mid)
    b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"), weight=10)
    b.place(Part("u2"), at=Polar((0.0, 6.0), None, about=mid), priority=Priority.HIGH, step=1.0)
    b.place(Part("m1"), priority=Priority.HIGH, face=Face.EITHER, step=1.0)
    return b.resolve()


def test_a_sensitive_part_placed_first_leaves_its_source_a_spot():
    plan = _sensitive_first()
    assert plan.placement("u2") is not None and plan.placement("m1") is not None, plan.findings
    assert _gap(plan) >= REACH - 1e-6


def test_a_sensitive_part_placed_first_needs_the_look_ahead():
    plan = _sensitive_first(dataclasses.replace(Settings(), place_lookahead=False))
    assert plan.placement("u2") is not None and plan.placement("m1") is None


def test_a_partner_that_cannot_fit_whatever_the_source_does_leaves_the_source_placed():
    """No spot of the disc is 25.1 mm from any spot the source may take: the source is still placed, as before."""
    b = _board(band=(0.0, 0.5))
    plan = b.resolve()
    assert plan.placement("m1") is not None
    assert plan.placement("u2") is None


def test_an_explore_variant_draws_only_among_spots_that_leave_the_partner_room():
    from placemat.explore import Explore
    for seed in (1, 2, 3):
        plan = _board().resolve(explore=Explore(seed, frozenset({"m1"})))
        assert plan.placement("m1") is not None and plan.placement("u2") is not None, (seed, plan.findings)
        assert _gap(plan) >= REACH - 1e-6


def test_the_native_sweep_and_the_python_sweep_choose_alike(monkeypatch):
    from placemat import placer
    native = _board().resolve()
    monkeypatch.setattr(placer, "NATIVE_SWEEP", False)
    python = _board().resolve()
    assert native.placement("m1") == python.placement("m1") and native.placement("u2") == python.placement("u2")


def _said(plan, needle, kind=None):
    return [f for f in plan.findings if needle in f and (kind is None or f.kind == kind)]


def test_a_dropped_look_ahead_is_a_finding_naming_the_pair_and_the_shortfall():
    plan = _board(band=(0.0, 0.5)).resolve()
    assert plan.placement("u2") is None
    found = _said(plan, "look-ahead was dropped")
    assert len(found) == 1, plan.findings
    text = str(found[0])
    assert text.startswith("m1: ") and "M1" in text and "U2" in text
    short, asked = [float(x) for x in re.search(r"left U2 ([\d.]+) mm short of ([\d.]+) mm", text).groups()]
    assert short > 0 and abs(asked - REACH) < 0.2
    step = next(s for s in plan.steps if s.item == "m1")
    assert "look-ahead was dropped" in step.note


def test_the_partner_that_then_fails_points_back_at_the_finding():
    plan = _board(band=(0.0, 0.5)).resolve()
    refusal = _said(plan, "see: no room was left for it when M1 was placed", "unplaced")
    assert len(refusal) == 1 and refusal[0].startswith("u2: "), plan.findings
    assert "see: no room was left for it when M1 was placed" in next(s for s in plan.steps if s.item == "u2").note


def test_a_pair_with_room_has_no_such_finding():
    plan = _board().resolve()
    assert not _said(plan, "look-ahead") and not _said(plan, "no room was left")


def test_a_partner_whose_room_was_taken_after_the_look_ahead_says_so():
    """The look-ahead leaves U2 room near a point, then a part placed in between sits on it."""
    spot = Near(Location(43.0, 24.0), radius=3.0, step=1.0)
    fps = _fps() + [footprint("X1", 70, 40, w=6, h=6, inst="x1", nets=("Q", "GND"))]
    b = Board(board_geometry(fps, width=80, height=80), edge_margin=0.4, keep_going=True)
    b.disc(2 * R)
    b.place(Part("m1"), at=Polar((0.0, 6.0), None, about=CENTRE), priority=Priority.HIGH, step=1.0)
    b.place(Part("x1"), at=Near(Location(43.0, 24.0), radius=1.0, step=1.0), priority=Priority.DEFAULT)
    b.place(Part("u2"), at=spot, priority=Priority.LOW)
    plan = b.resolve()
    assert plan.placement("m1") is not None
    assert not _said(plan, "look-ahead was dropped"), plan.findings
    refusal = _said(plan, "what was placed since took it")
    assert refusal and refusal[0].startswith("u2: "), plan.findings


def test_a_sensitive_member_of_a_cell_needs_only_its_own_body_outside_the_disc():
    """The source looks ahead for room for the sensitive member alone, as the push's disc fences it alone: the
    cell's other members may stand inside the disc, so a cell longer than the room outside it still fits radially."""
    from placemat.values import Cell
    m1 = footprint("M1", 70, 10, w=4, h=4, inst="m1", nets=("A", "GND"), fields={"Pm.Emits": EMITS})
    u2 = footprint("U2", 1, 1, w=2, h=2, inst="sensor.u2", nets=("SIG", "GND"), cell="sensor", fields={"Pm.Limit": LIMIT})
    u3 = footprint("U3", 13, 1, w=3, h=3, inst="sensor.u3", nets=("SIG2", "GND"), cell="sensor")
    b = Board(board_geometry([m1, u2, u3], cells=["sensor"], width=80, height=80), edge_margin=0.4, keep_going=True)
    b.disc(2 * R)
    b.place(Part("m1"), at=Polar((0.0, 6.0), None, about=CENTRE), priority=Priority.HIGH, step=1.0)
    b.place(Cell("sensor"), priority=Priority.LOW, step=1.0)
    plan = b.resolve()
    assert plan.placement("sensor") is not None, plan.findings
    assert not any("look-ahead" in f or "short of" in f for f in plan.findings), plan.findings
