"""A carried via inside a pad of its own net with no spot clear there leaves the pad, joined to it by
a new tail (docs/superpowers/specs/2026-10-01-in-pad-via-leaves-its-pad-design.md)."""
import dataclasses

import pytest

from placemat.board_geometry import NetClass
from placemat.copper import Track, Via
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Face, Location, Near, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint, rect, track

F, B = CopperLayer.F, CopperLayer.B


def _with_pad(fp, number, w, h):
    """`fp` with its pad `number` of size w x h about the same centre."""
    pads = []
    for p in fp.pads:
        if p.number == str(number):
            c = p.box.center
            outline = rect(c.x, c.y, w, h)
            p = dataclasses.replace(p, outlines=(outline,), box=Box.of_points(outline))
        pads.append(p)
    return dataclasses.replace(fp, pads=tuple(pads))


def _board(settings=None, copper=(), tiers=None, geometry_kw=None, q_at=20.0):
    """P on the back, its GND pad 0.80 x 0.95 mm at (18.6, 20) with one in-pad plane drop; Q on the
    front, searched with no room to move, its pad 1 (1 x 1 mm) over it: a drop 0.45 mm across has
    0.175 x 0.25 mm of play, and no spot in it clears Q's pad. Both are searched, which is what
    makes P carry its via."""
    p = _with_pad(footprint("P", 20, 20, w=4, h=2, inst="p", nets=("GND", "X"), face=Face.BACK), 1, 0.8, 0.95)
    q = footprint("Q", q_at, 20, w=4, h=2, inst="q", nets=("Y", "Z"))
    g = board_geometry([p, q], copper=list(copper), width=50, height=50, extra_nets=("GND",))
    if geometry_kw:
        g = dataclasses.replace(g, **geometry_kw)
    b = Board(g, edge_margin=0.5, keep_going=True, settings=settings or Settings(), fab_via_tiers=tiers or {})
    b.plane(Net("GND"), [B])
    b.place(Part("p"), at=Near(Location(20, 20), radius=0, rotations=(0,)), face=Face.BACK)
    b.via(Net("GND"), PadRef(Part("p"), 1), size=0.45, drill=0.2)
    b.place(Part("q"), at=Near(Location(q_at, 20), radius=0, rotations=(0,)))
    return b


def _wide_net():
    """Geometry changes: GND's track width 0.5 mm, the board's minimum 0.1."""
    classes = {n: NetClass("Default", 0.5 if n == "GND" else 0.2, 0.2, 0.6, 0.3) for n in ("GND", "X", "Y", "Z")}
    return {"netclasses": classes, "min_track_width": 0.1}


# a sliver of another net's copper beside the corridor between the via and its pad
_SLIVER = track("Y", 17.955, 20.375, 17.955, 20.9, w=0.07, layer=B)


def _tracks(plan):
    return [c for c in plan.copper if isinstance(c, Track)]


def _vias(plan):
    return [c for c in plan.copper if isinstance(c, Via)]


def _inside(poly, p):
    from placemat.geometry import point_in_polygon
    return point_in_polygon(p, poly)


def test_a_via_with_no_spot_in_its_pad_leaves_it_joined_by_a_tail():
    plan = _board().resolve()
    step = plan.step("q")
    assert step.placement is not None, step.note
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.via, a.net, a.under, a.pad) == ("leave", "pad via 0", "GND", "Q", ("P", "1"))
    assert a.cost == pytest.approx(4.0)
    [t] = _tracks(plan)
    [v] = _vias(plan)
    assert a.tail == t and (v.at.x, v.at.y) == a.to
    assert (t.layer, t.width) == (B, 0.2)                       # the pad's face, the net's width
    assert (v.size, v.drill) == (0.45, 0.2)
    pad1 = next(x for x in plan.occupancy.items["P"].shapes if x.kind == "pad" and x.label == "1")
    assert _inside(pad1.poly, (t.start.x, t.start.y))            # the tail starts in the pad's copper
    assert not _inside(pad1.poly, (v.at.x, v.at.y))              # and the via stands outside it
    assert (t.end.x, t.end.y) == (v.at.x, v.at.y)
    assert not [f for f in plan.findings if f.kind in ("copper", "unplaced", "fixed")], list(plan.findings)


def test_the_report_names_a_via_that_left_its_pad():
    from placemat import giveway
    plan = _board().resolve()
    from placemat.finding_text import vias_note
    assert [(h, vias_note(f), s) for h, f, s in giveway.report(plan.occupancy)] == [("P", "1 GND via left its pad under Q", "notice")]


def test_a_pad_with_room_inside_still_moves_inside():
    """Q's pad lies further east: the via moves 0.15 mm west, inside its pad, with no tail."""
    plan = _board(q_at=20.8).resolve()
    assert plan.step("q").placement is not None, plan.step("q").note
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.to, a.tail) == ("move", (18.45, 20.0), None)
    assert not _tracks(plan)


def test_via_leave_zero_leaves_nothing():
    plan = _board(settings=Settings(place_via_leave=0.0)).resolve()
    step = plan.step("q")
    assert step.placement is None
    assert "no spot within 0.50 mm inside its pad is clear" in step.note, step.note
    assert "leave its pad" not in step.note


def test_a_via_that_cannot_reach_a_clear_spot_is_refused_and_says_so():
    plan = _board(settings=Settings(place_via_leave=0.6)).resolve()
    step = plan.step("q")
    assert step.placement is None
    assert "no spot within 0.60 mm is clear to leave its pad by a tail" in step.note, step.note


def test_leaving_costs_score_via_leave():
    plan = _board(settings=Settings(score_via_leave=7.0)).resolve()
    [a] = plan.occupancy.given_way.values()
    assert a.cost == 7.0


def test_leaving_costs_more_than_a_move_and_less_than_shortening_and_a_drop():
    s = Settings()
    assert s.score_via_move < s.score_via_leave < s.score_via_shorten < s.score_via_drop


def test_the_tail_is_narrower_where_a_neighbour_needs_it():
    """The net's width is 0.5 mm; the sliver keeps a tail 0.2 mm off at 0.25 mm."""
    plan = _board(copper=[_SLIVER], geometry_kw=_wide_net()).resolve()
    assert plan.step("q").placement is not None, plan.step("q").note
    [a] = plan.occupancy.given_way.values()
    assert (a.kind, a.to) == ("leave", (17.65, 20.0))
    assert a.tail.width == pytest.approx(0.25)


def test_the_tail_is_never_narrower_than_the_boards_minimum():
    kw = dict(_wide_net(), min_track_width=0.3)
    plan = _board(copper=[_SLIVER], geometry_kw=kw).resolve()
    [a] = plan.occupancy.given_way.values()
    assert a.kind == "leave" and a.tail.width >= 0.3 - 1e-9 and a.to != (17.65, 20.0)


def test_tail_widths_step_down_from_the_nets_width_to_the_minimum():
    from placemat import giveway
    from placemat.occupancy import Occupancy
    g = board_geometry([footprint("P", 20, 20, nets=("GND", "X"))], width=50, height=50)
    assert giveway._tail_widths(Occupancy(g), "GND") == (0.2,)                       # the minimum is not known
    assert giveway._tail_widths(Occupancy(dataclasses.replace(g, min_track_width=0.1)), "GND") == (0.2, 0.15, 0.1)
    assert giveway._tail_widths(Occupancy(dataclasses.replace(g, min_track_width=0.12)), "GND") == (0.2, 0.15, 0.12)
    assert giveway._tail_widths(Occupancy(dataclasses.replace(g, min_track_width=0.3)), "GND") == (0.2,)


def test_a_cells_via_in_its_pad_leaves_it_and_the_plan_draws_the_tail():
    from tests.test_vias_give_way import _moving_board
    plan = _moving_board((39.1, 40.0), False, (20.1, 20.0)).resolve()
    assert plan.step("m").placement is not None, plan.step("m").note
    [a] = plan.occupancy.given_way.values()
    assert a.kind == "leave" and a.tail is not None and a.tail in plan.copper
    assert (a.tail.start.x, a.tail.start.y) == (19.1, 20.0)
    assert (a.tail.end.x, a.tail.end.y) == a.to
    [ring] = [c for c in plan.occupancy.copper if c.owner == "m" and c.kind == "through"]
    assert ring.points == (a.to,)


def test_a_via_outside_its_pad_does_not_leave_it():
    """Its tail ends in the pad and the via is outside it: a move handles that."""
    from tests.test_vias_give_way import _moving_board
    plan = _moving_board((39.1, 42.2), True, (19.5, 23.0), settings=Settings(place_via_move=0.1)).resolve()
    step = plan.step("m")
    assert step.placement is None and "leave its pad" not in step.note, step.note


# ------------------------------------------------------------------ native and Python agree
def test_leaving_is_the_same_native_or_not(monkeypatch):
    from tests.test_vias_give_way import _first_move_runs
    runs = _first_move_runs(monkeypatch, _board)
    assert runs[True][:2] == runs[False][:2]
    assert runs[False][2] == 0
    assert runs[True][2] >= 1, "the native first_move judged no leave"
    assert [row[0] for row in runs[True][0]] == ["leave"]


def test_a_narrowed_leave_is_the_same_native_or_not(monkeypatch):
    from tests.test_vias_give_way import _first_move_runs
    runs = _first_move_runs(monkeypatch, lambda: _board(copper=[_SLIVER], geometry_kw=_wide_net()))
    assert runs[True][:2] == runs[False][:2]
    assert runs[True][2] >= 1


# ------------------------------------------------------------------ KiCad's DRC on the written board
_RULES = {"clearance", "shorting_items", "unconnected_items", "hole_clearance", "hole_to_hole"}


def _drc(tmp_path, plan):
    import json
    import subprocess
    pcbnew = pytest.importorskip("pcbnew")

    def mm(v):
        return pcbnew.FromMM(v)
    board = pcbnew.CreateEmptyBoard()
    nets = {}

    def net(n):
        if n not in nets:
            nets[n] = pcbnew.NETINFO_ITEM(board, n)
            board.Add(nets[n])
        return nets[n]
    for fp in plan.geometry.footprints:
        place = plan.placement(fp.inst)
        assert (place.location.x, place.location.y, place.face) == (fp.location.x, fp.location.y, fp.face)
        kfp = pcbnew.FOOTPRINT(board)
        kfp.SetReference(fp.ref)
        kfp.SetPosition(pcbnew.VECTOR2I(mm(fp.location.x), mm(fp.location.y)))
        for p in fp.pads:
            kp = pcbnew.PAD(kfp)
            kp.SetShape(pcbnew.PAD_SHAPE_RECT)
            kp.SetSize(pcbnew.VECTOR2I(mm(p.box.width), mm(p.box.height)))
            kp.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            ls = pcbnew.LSET()
            ls.AddLayer(pcbnew.F_Cu if fp.face is Face.FRONT else pcbnew.B_Cu)
            kp.SetLayerSet(ls)
            kp.SetPosition(pcbnew.VECTOR2I(mm(p.box.center.x), mm(p.box.center.y)))
            kp.SetNumber(str(p.number))
            kp.SetNet(net(p.net))
            kfp.Add(kp)
        board.Add(kfp)
    for op in plan.copper:
        if isinstance(op, Via):
            kv = pcbnew.PCB_VIA(board)
            kv.SetPosition(pcbnew.VECTOR2I(mm(op.at.x), mm(op.at.y)))
            kv.SetWidth(mm(op.size))
            kv.SetDrill(mm(op.drill))
            kv.SetNet(net(op.net))
            board.Add(kv)
        elif isinstance(op, Track):
            kt = pcbnew.PCB_TRACK(board)
            kt.SetStart(pcbnew.VECTOR2I(mm(op.start.x), mm(op.start.y)))
            kt.SetEnd(pcbnew.VECTOR2I(mm(op.end.x), mm(op.end.y)))
            kt.SetWidth(mm(op.width))
            kt.SetLayer(pcbnew.F_Cu if op.layer is F else pcbnew.B_Cu)
            kt.SetNet(net(op.net))
            board.Add(kt)
    pcb = tmp_path / "board.kicad_pcb"
    board.Save(str(pcb))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    found = json.loads(report.read_text())
    return [v for key in ("violations", "unconnected_items") for v in found.get(key, []) if v.get("type") in _RULES]


def test_kicad_finds_no_clearance_or_unconnected_error_with_the_via_out_of_its_pad(tmp_path):
    plan = _board().resolve()
    assert [a.kind for a in plan.occupancy.given_way.values()] == ["leave"]
    assert _drc(tmp_path, plan) == []


def test_kicad_flags_the_via_left_unjoined_as_a_control(tmp_path):
    """The same board without the tail has an unconnected via: the check does judge the join."""
    plan = _board().resolve()
    plan.copper = [c for c in plan.copper if not isinstance(c, Track)]
    assert [v for v in _drc(tmp_path, plan) if v["type"] == "unconnected_items"]
