"""A part's `board.vias()` grid is carried with its part, and gives way as a stamped cell's field does
(docs/superpowers/specs/2026-10-01-carried-via-grids-design.md)."""
import dataclasses

import pytest

from placemat.board_geometry import Footprint
from placemat.copper import Via
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Face, Location, Near, Net, PadRef, Part
from tests.fixtures import board_geometry, pad

NO_LEAVE = Settings(place_via_leave=0.0)
SIZE, DRILL = 0.45, 0.2


def _u1(w=2.4, h=2.4, net="GND"):
    """U1: a pad of `net` `w` x `h` centred on (20, 20), and a SIG pad south of it."""
    pads = (pad("U1", "u1", 1, net, 20, 20, w, h), pad("U1", "u1", 2, "SIG", 20, 23, 1, 1))
    body = Box.union([p.box for p in pads]).inflate(0.5)
    return Footprint("U1", "u1", None, "U1", body.center, 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)


def _r(ref, cx, cy, w, h, net="S"):
    """`ref`: one pad `w` x `h` at (cx, cy) on the back."""
    p = pad(ref, ref.lower(), 1, net, cx, cy, w, h, False, Face.BACK)
    body = p.box
    return Footprint(ref, ref.lower(), None, ref, Location(cx, cy), 0.0, Face.BACK, body, body.inflate(0.1), body, (p,))


def _board(backs, *, pitch=0.8, inset=0.0, net="GND", settings=None, planes=("GND",), u1=None, searched_u1=False,
           searched_backs=False, vias=True, vias_first=False):
    """U1 (a grid of `net` vias in its pad 1) and a part on the back for each of `backs`
    ((cx, cy, w, h)). U1 stands firmly at (20, 20) unless `searched_u1`; the back parts are firm at their
    pads unless `searched_backs`, and are declared after U1 unless U1 is searched."""
    u1 = u1 or _u1()
    fps = [u1] + [_r("R%d" % (9 + k), *b) for k, b in enumerate(backs)]
    g = board_geometry(fps, width=40, height=40, extra_nets=(net, "S"))
    g = dataclasses.replace(g, hole_to_hole=0.25)
    kw = {"settings": settings} if settings is not None else {}
    b = Board(g, edge_margin=0.5, keep_going=True, **kw)
    for n in planes:
        b.plane(Net(n), [CopperLayer.B])
    c = u1.body_box.center
    place_u1 = lambda: b.place(Part("u1"), at=Near(Location(c.x, c.y), radius=0, rotations=(0,)) if searched_u1
                               else Location(c.x, c.y))
    place_back = lambda: [b.place(Part("r%d" % (9 + k)), at=Near(Location(r[0], r[1]), radius=0, rotations=(0,))
                                  if searched_backs else Location(r[0], r[1]), face=Face.BACK)
                          for k, r in enumerate(backs)]
    def declare():
        kw = dict(pitch=pitch, size=SIZE, drill=DRILL)
        if inset:
            kw["inset"] = inset
        b.vias(Net(net), PadRef(Part("u1"), 1), **kw)
    if vias and vias_first:
        declare()
    if searched_u1:
        place_back()
        place_u1()
    else:
        place_u1()
        place_back()
    if vias and not vias_first:
        declare()
    return b


def _drawn(plan, net="GND"):
    return sorted((round(v.at.x, 3), round(v.at.y, 3)) for v in plan.copper if isinstance(v, Via) and v.net == net)


def _gave(plan):
    return sorted(plan.occupancy.given_way.values(), key=lambda a: a.via)


def _vias_findings(plan):
    return [str(f) for f in plan.findings if f.kind == "vias"]


AS_DRAWN = sorted((x, y) for x in (19.2, 20.0, 20.8) for y in (19.2, 20.0, 20.8))
TOP_ROW = (20.0, 19.2, 2.8, 0.3)           # a pad on the back along the north row of the grid


def test_the_grid_is_drawn_as_before_where_nothing_meets_it():
    plan = _board([(30.0, 30.0, 1.0, 1.0)]).resolve()
    assert _drawn(plan) == AS_DRAWN
    assert not plan.occupancy.given_way
    assert "in the pad" in plan.step("vias GND").note


def test_a_grid_on_a_firmly_placed_part_is_re_laid_for_a_far_face_pad_placed_after_it():
    plan = _board([TOP_ROW], settings=NO_LEAVE).resolve()
    assert plan.step("r9").placement is not None, plan.step("r9").note
    steps = _gave(plan)
    assert {a.kind for a in steps} == {"relay-move"} and {a.way for a in steps} == {"close the pitch"}
    assert (steps[0].before, steps[0].after, steps[0].want) == (9, 9, 9)
    assert {a.field for a in steps} == {"field U1 U1.1"}
    got = _drawn(plan)
    assert len(got) == 9 and got != AS_DRAWN
    assert sorted({y for _, y in got}) == [19.8, 20.3, 20.8]
    assert not [f for f in plan.findings if f.kind in ("copper", "unplaced", "fixed")], list(plan.findings)
    assert _vias_findings(plan) == ["u1: GND field in U1 pad 1 re-laid by close the pitch, 9 vias before, 9 after under R9"]


def test_the_grid_of_a_part_the_search_has_placed_gives_way_to_a_part_searched_after_it():
    plan = _board([TOP_ROW], settings=NO_LEAVE, searched_backs=True).resolve()
    assert plan.step("r9").placement is not None, plan.step("r9").note
    assert len(_drawn(plan)) == 9
    assert {a.kind for a in _gave(plan)} == {"relay-move"}
    assert {a.field for a in _gave(plan)} == {"field U1 U1.1"}


def test_a_searched_part_carries_its_grid_to_where_it_lands_and_the_grid_gives_way_there():
    plan = _board([TOP_ROW], settings=NO_LEAVE, searched_u1=True).resolve()
    assert plan.step("u1").placement is not None, plan.step("u1").note
    assert {a.kind for a in _gave(plan)} == {"relay-move"}
    assert len(_drawn(plan)) == 9
    assert not [f for f in plan.findings if f.kind in ("copper", "fixed")], list(plan.findings)


def test_a_searched_part_s_grid_is_laid_whole_where_nothing_is_in_its_way():
    plan = _board([(30.0, 30.0, 1.0, 1.0)], searched_u1=True).resolve()
    assert len(_drawn(plan)) == 9 and not plan.occupancy.given_way


def test_a_grid_with_no_room_is_dropped_to_the_floor_and_reports_what_the_pad_holds():
    plan = _board([(20.0, 19.2, 2.8, 0.3)], pitch=0.45, settings=NO_LEAVE, u1=_u1(1.5, 1.5)).resolve()
    assert plan.step("r9").placement is not None, plan.step("r9").note
    assert {a.kind for a in _gave(plan)} == {"drop"} and len(_gave(plan)) == 3
    assert len(_drawn(plan)) == 6
    assert _vias_findings(plan) == ["u1: 3 GND vias dropped under R9 (U1 pad 1 holds 6 of 9)"]
    assert not [f for f in plan.findings if f.kind in ("copper", "fixed")], list(plan.findings)


def test_a_grid_of_a_net_that_is_no_plane_is_never_dropped_and_refuses_the_spot():
    plan = _board([(20.0, 19.2, 2.8, 0.3)], pitch=0.45, net="SIG2", planes=(), settings=NO_LEAVE,
                  u1=_u1(1.5, 1.5, "SIG2")).resolve()
    assert "SIG2 is not a plane net, so it is no drop" in plan.step("r9").note, plan.step("r9").note
    assert any(f.kind == "fixed" for f in plan.findings)
    assert not plan.occupancy.given_way


def test_with_the_relay_off_the_row_is_dropped_as_before():
    plan = _board([TOP_ROW], settings=Settings(place_via_leave=0.0, place_via_relay=False)).resolve()
    assert {a.kind for a in _gave(plan)} == {"drop"}
    assert len(_drawn(plan)) == 6


def test_a_relay_keeps_the_inset_the_grid_was_declared_with():
    """Declared with `inset=0.1`: a via's copper, grown by 0.1, lies in the land; a re-laid site keeps that."""
    plan = _board([TOP_ROW], pitch=0.8, inset=0.1, settings=NO_LEAVE, u1=_u1(2.6, 2.6)).resolve()
    got = _drawn(plan)
    assert len(got) == 9
    assert all(abs(x - 20.0) + SIZE / 2 + 0.1 <= 1.3 + 1e-6 and abs(y - 20.0) + SIZE / 2 + 0.1 <= 1.3 + 1e-6
               for x, y in got), got


def test_a_relay_does_not_close_the_pitch_below_what_pitch_is_refused_under():
    """The floor of `pitch=` is max(size, drill + hole-to-hole): 0.45 here. A pad that would need 0.4 loses vias."""
    plan = _board([(20.0, 19.2, 2.8, 0.65)], pitch=0.8, settings=NO_LEAVE).resolve()
    ys = sorted({y for _, y in _drawn(plan)})
    gaps = [b - a for a, b in zip(ys, ys[1:])]
    assert all(g >= 0.45 - 1e-6 for g in gaps), ys


def test_undo_puts_a_grid_that_was_re_laid_back_as_drawn():
    from placemat import giveway
    plan = _board([TOP_ROW], settings=NO_LEAVE).resolve()
    occ = plan.occupancy
    assert occ.given_way
    via = next(iter(occ.given_way))
    giveway.undo(occ, via)
    assert not occ.given_way
    carried = sorted((round(c.points[0][0], 3), round(c.points[0][1], 3)) for c in occ.items["U1"].shapes
                     if c.carried and c.kind == "through")
    assert carried == AS_DRAWN


def test_a_grid_is_a_late_intent_whatever_its_part_and_the_pour_that_names_it_is_late_too():
    b = _board([(30.0, 30.0, 1.0, 1.0)])
    grid = b._copper[-1]
    assert grid.key == "vias GND"
    b.pour(Net("GND"), [grid, PadRef(Part("u1"), 1)], layer=CopperLayer.F, swallow_pads=True)
    b.resolve()
    assert not grid.freedom.decided
    assert not b._copper[-1].freedom.decided


def test_a_pad_too_small_for_a_via_still_says_no_via_fits():
    plan = _board([(30.0, 30.0, 1.0, 1.0)], u1=_u1(0.4, 0.4)).resolve()
    assert not _drawn(plan) and any("no via fits" in str(f) for f in plan.findings)


def test_a_row_along_a_pads_axis_is_not_carried():
    b = _board([(30.0, 30.0, 1.0, 1.0)], vias=False)
    b.vias(Net("GND"), along=PadRef(Part("u1"), 1), count=2, size=SIZE, drill=DRILL)
    plan = b.resolve()
    assert not [c for g in plan.occupancy.items.values() for c in g.shapes if c.carried]
    assert len(_drawn(plan)) == 2


@pytest.mark.parametrize("flags", [dict(), dict(_NATIVE_MOVE_SEARCH=False), dict(_NATIVE_FIRST_MOVE=False),
                                   dict(_NATIVE_TAIL_CLEAR=False, _NATIVE_MOVE_SEARCH=False, _NATIVE_FIRST_MOVE=False)])
def test_a_grid_is_re_laid_the_same_whichever_native_calls_judge_the_vias_beside_it(monkeypatch, flags):
    from placemat import giveway
    want = _drawn(_board([TOP_ROW], settings=NO_LEAVE).resolve())
    for name, value in flags.items():
        monkeypatch.setattr(giveway, name, value)
    assert _drawn(_board([TOP_ROW], settings=NO_LEAVE).resolve()) == want


def test_a_rider_placed_on_its_hosts_pad_is_judged_with_the_grid_giving_way_to_it_not_refused_by_it():
    """A part put by a pin on a pad of a part that carries a grid is a rider: it is settled with its host. The
    host's vias are not what refuses it; they give way when it is committed."""
    from placemat import Along, Edge, Pin
    g = board_geometry([_u1(), _r("R9", 30, 30, 2.8, 0.3)], width=40, height=40, extra_nets=("GND", "S"))
    g = dataclasses.replace(g, hole_to_hole=0.25)
    b = Board(g, edge_margin=0.5, keep_going=True, settings=NO_LEAVE)
    b.plane(Net("GND"), [CopperLayer.B])
    b.place(Part("u1"), at=Location(20.0, 21.5))
    b.place(Part("r9"), at=Pin(1, PadRef(Part("u1"), 1, edge=Edge.NORTH, along=Along.MID)), face=Face.BACK)
    b.vias(Net("GND"), PadRef(Part("u1"), 1), pitch=0.8, size=SIZE, drill=DRILL)
    plan = b.resolve()
    assert plan.step("u1").placement is not None and plan.step("r9").placement is not None
    assert plan.step("r9").note == "" or "rides" in plan.step("r9").note
    assert plan.occupancy.given_way and len(_drawn(plan)) >= 6
    assert not [f for f in plan.findings if f.kind in ("copper", "fixed", "unplaced")], list(plan.findings)


@pytest.mark.parametrize("kw", [dict(), dict(searched_u1=True), dict(searched_backs=True)])
def test_where_the_grid_is_declared_among_the_places_changes_nothing(kw):
    after = _board([TOP_ROW], settings=NO_LEAVE, **kw).resolve()
    first = _board([TOP_ROW], settings=NO_LEAVE, vias_first=True, **kw).resolve()
    assert _drawn(first) == _drawn(after) and len(_drawn(first)) == 9
    assert [(a.kind, a.via) for a in _gave(first)] == [(a.kind, a.via) for a in _gave(after)]


def test_a_grid_of_a_net_that_is_no_plane_is_re_laid_where_there_is_room():
    plan = _board([TOP_ROW], net="SIG2", planes=(), settings=NO_LEAVE, u1=_u1(2.4, 2.4, "SIG2")).resolve()
    assert {a.kind for a in _gave(plan)} == {"relay-move"}
    assert len(_drawn(plan, "SIG2")) == 9
