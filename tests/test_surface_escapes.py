"""Escapes judged by surface lanes (docs/superpowers/specs/2026-10-07-surface-escapes-design.md): a pad's way out is a
straight lane on its own layer toward what it joins (free), else a via beside it (score.escape_via), else a lane another
way (score.escape_closed), else none (score.escape_walled)."""
import dataclasses

import pytest

from placemat.escapes import Way, judging, pad_lanes, price, _pads_of
from placemat.settings import Settings
from placemat.values import Net
from tests.escape_fixtures import PIN1_EDGE, PIN1_Y, ic_with_cap, ic_with_cap_board


def test_cap_across_the_normal_closes_the_straight_lane_but_not_the_45():
    occ, esc = ic_with_cap(offset_mm=1.5, lateral_mm=0.0, room=True)
    lanes = esc.lanes("U1", "1")
    west = next(l for l in lanes if l.direction == pytest.approx((-1.0, 0.0)))
    assert not esc.lane_open(west)
    assert any(esc.lane_open(l) and l.direction[0] < -0.5 and l.direction[1] != 0 for l in lanes)
    assert esc.judge("U1", "1") is Way.SURFACE


def test_with_the_diagonals_closed_the_lane_north_along_the_row_end_is_the_way_toward_the_target():
    """C2 and C3 close both diagonals west; the lane north along the row's end runs to the window's edge west of the pad's
    centre, which the path search counts as toward the target too."""
    occ, esc = ic_with_cap(offset_mm=1.0, lateral_mm=0.0, room=False)
    assert not any(esc.lane_open(l) for l in esc.lanes("U1", "1") if l.direction[0] < -0.5)
    north = next(l for l in esc.lanes("U1", "1") if l.direction == pytest.approx((0.0, -1.0)))
    assert esc.lane_open(north) and north.legs[1][1][0] < 27.3
    assert esc.judge("U1", "1") is Way.SURFACE


def test_where_no_lane_gets_out_the_path_search_decides():
    """The ring's pads 1.0 mm off: every straight lane meets a ring pad, and the search finds a track out through the
    gaps between them."""
    from tests.test_escape_findings import _walled_in
    occ = _via_only_board(_walled_in(1.0)).resolve().occupancy
    esc = judging(occ)
    assert not esc.lane_check("U9", "1")[1]
    ways = {(r, n): w for r, n, _, w, _ in esc.judged()}
    assert ways[("U9", "1")] is Way.SURFACE
    esc.searched = 0
    assert esc.judge("U9", "1") is Way.SURFACE and esc.searched == 1


def _via_only(gap=0.8):
    """U9's IN pad ringed `gap` mm off by R9's pads (tests.test_escape_findings._walled_in): the slits between the ring's
    pads are under a track and its clearances, and a via fits at the pad's edge."""
    from tests.test_escape_findings import _walled_in
    return _via_only_board(_walled_in(gap))


def _via_only_board(fps):
    import dataclasses as dc
    from placemat.layout import Board
    from placemat.values import Part
    from tests.fixtures import board_geometry
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0,
              settings=dc.replace(Settings(), cleanup_enabled=False), keep_going=True)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    return b


def test_a_pad_with_no_surface_way_out_and_a_via_spot_leaves_by_a_via():
    occ = _via_only().resolve().occupancy
    assert judging(occ).judge("U9", "1") is Way.VIA
    assert price(Way.VIA, Settings()) == Settings().score_escape_via


def test_quiet_and_no_connect_pads_are_not_judged():
    occ, esc = ic_with_cap(offset_mm=1.5, lateral_mm=0.0, room=True, pin1_net="GND", plane=True)
    assert ("U1", "1") not in {(r, n) for r, n, *_ in esc.judged()}
    occ, esc = ic_with_cap(offset_mm=1.5, lateral_mm=0.0, room=True, pin1_net="NC_U1_1")
    assert ("U1", "1") not in {(r, n) for r, n, *_ in esc.judged()}


def test_a_pad_whose_net_has_no_other_pad_is_not_judged():
    occ, esc = ic_with_cap()
    assert ("U1", "1") in {(r, n) for r, n, *_ in esc.judged()}
    assert ("U1", "2") not in {(r, n) for r, n, *_ in esc.judged()}     # N2 has no other pad


def test_a_row_pad_has_eight_lanes_from_its_edge_reaching_out_to_the_setting():
    occ, esc = ic_with_cap()
    g = occ.items["U1"]
    lanes, spots = pad_lanes(occ, "U1", _pads_of(g.shapes, "U1"), g.reference.rotation)
    mine = [l for l in lanes if l.number == "1"]
    assert len(mine) == 8
    win = esc._lanes_of("U1")[2]["1"][2].inflate(Settings().score_escape_reach)      # the path search's window
    for l in mine:
        (a, b), (b2, end) = l.legs
        assert a == b == b2 == pytest.approx((PIN1_EDGE, PIN1_Y))       # pin 1 is the row's end: no field west of it
        assert min(abs(end[0] - win.left), abs(end[0] - win.right), abs(end[1] - win.top), abs(end[1] - win.bottom)) \
            == pytest.approx(0.0, abs=1e-9)                             # on the window's edge
    assert len([s for s in spots if s.number == "1"]) == 1          # a via touching the pad's edge along the normal


def test_on_a_fine_pitch_the_first_leg_runs_on_until_a_diagonal_clears_the_neighbours_tips():
    from placemat.values import Location, Part
    from tests.escape_fixtures import PAD_W, PD_NETS, PITCH, board_with, qfn, small_part
    b = board_with([qfn(nets=PD_NETS), small_part("T1", "t1", ("SENSE", "Z"), cx=30.0, cy=15.0)])
    b.place(Part("pd"), at=Location(30, 30))
    b.place(Part("t1"), at=Location(30, 15))
    occ = b.resolve().occupancy
    esc = judging(occ)
    (a, b), _ = esc.lanes("U1", "31")[0].legs                       # north row: pin 31's tip at y = 27.2
    assert a[1] == pytest.approx(27.2)
    half = 0.2 / 2 + 0.2                                            # track 0.2, clearance 0.2
    side = PITCH - PAD_W / 2                                        # to the neighbour's near corner
    assert a[1] - b[1] == pytest.approx(half * 2 ** 0.5 - side)
    g = occ.items["U1"]
    _, spots = pad_lanes(occ, "U1", _pads_of(g.shapes, "U1"), g.reference.rotation)
    assert len([s for s in spots if s.number == "31"]) == 2         # and one where the first leg leaves the field


def test_a_two_pad_part_has_no_first_leg_and_a_via_spot_on_three_sides():
    occ, esc = ic_with_cap()
    g = occ.items["T1"]
    lanes, spots = pad_lanes(occ, "T1", _pads_of(g.shapes, "T1"), g.reference.rotation)
    mine = [l for l in lanes if l.number == "1"]
    assert len(mine) == 8 and all(l.legs[0][0] == l.legs[0][1] for l in mine)
    assert len([s for s in spots if s.number == "1"]) == 3


def test_a_pad_with_no_via_room_and_no_lane_toward_its_target_is_closed_and_with_none_at_all_walled():
    from tests.test_escape_findings import _fixed, _walled_in
    plan = _fixed(_walled_in(0.1), keep_going=True)
    esc = judging(plan.occupancy)
    assert esc.judge("U9", "1") is Way.WALLED
    found = [str(f) for f in plan.findings if f.kind == "escape_walled"]
    assert found == ["U9 pin 1 (IN): walled off by R9"]


def test_a_via_only_pad_is_reported_escape_via_naming_what_blocks_its_lanes():
    plan = _via_only().resolve()
    vias = [f for f in plan.findings if f.kind == "escape_via"]
    assert [(f.facts["ref"], f.facts["pin"], f.facts["net"]) for f in vias] == [("U9", "1", "IN")]
    assert {b.get("name") for b in vias[0].facts["by"]} == {"R9"}
    assert vias[0].severity == "warning"
    assert str(vias[0]) == "U9 pin 1 (IN): leaves only by a via, its straight lanes closed by R9"


def test_the_lanes_keep_the_class_clearance_as_the_path_search_does():
    """A script's wider clearance between the pad's net and C1's does not close a lane: the path search keeps the net
    class's clearance, and the lanes are a first check that may only find what it finds."""
    def open_45s(b):
        esc = judging(b.resolve().occupancy)
        return [l.direction for l in esc.lanes("U1", "1") if esc.lane_open(l) and l.direction[0] < -0.5 and l.direction[1]]
    plain = open_45s(ic_with_cap_board(offset_mm=1.5, room=True))
    b = ic_with_cap_board(offset_mm=1.5, room=True)
    b.rule(clearance=0.6, between=(Net("SIG"), Net("CA")), why="a wider gap to C1")
    b.rule(clearance=0.6, between=(Net("SIG"), Net("CB")), why="a wider gap to C1")
    assert plain and open_45s(b) == plain


def test_the_run_score_prices_the_judgement_and_whole_agrees_with_the_plan():
    from placemat import score
    b = _via_only()
    plan = b.resolve()
    m = score.plan_measures(b, plan)
    assert m["findings"].get("escape_via") == 1
    t = score.terms(m, b.settings)
    assert t["escape_via"] == pytest.approx(b.settings.score_escape_via)
    w = score.whole(b, plan.occupancy, plan)
    for k in ("escape_crossed", "escape_closed", "escape_via"):
        assert w[k] == pytest.approx(t[k]), k
    assert "escape_walled" not in w                     # a walled pad is the validity tier's, not a run-score term


def test_a_plane_pad_is_judged_for_walled_only():
    """A quiet net's pad drops to its plane by a via: with a via spot it is not reported, with none and no surface
    route it is walled."""
    from tests.test_escape_walled_joined import _module
    assert [str(f) for f in _module(False).findings if f.kind.startswith("escape_")] == [
        "U9 pin GND (GND): walled off by N1"]
    occ, esc = ic_with_cap(pin1_net="GND", plane=True)
    assert esc.judge("U1", "1") is None


def test_the_settings_default_as_decided():
    s = Settings()
    assert s.score_escape_reach == 3.0 and s.score_escape_via == 10.0
    assert price(Way.SURFACE, s) == 0.0
    assert price(Way.AWAY, s) == s.score_escape_closed
    with pytest.raises(ValueError, match="validity"):
        price(Way.WALLED, s)
    cfg = dataclasses.replace(s, score_escape_via=7.0)
    assert price(Way.VIA, cfg) == 7.0


def test_a_pad_whose_only_surface_way_runs_away_from_its_target_is_closed():
    """U9's IN pad ringed 0.1 mm off by R9 but for the ring's east pad, with two Z tracks carrying that gap out east to
    the window's edge, and T1, what IN joins, 20 mm west: the track gets out only eastward, and no via spot clears the
    ring's corner pads."""
    import dataclasses as dc
    from placemat.board_geometry import Footprint
    from placemat.values import CopperLayer, Location
    from tests.fixtures import footprint
    from tests.test_escape_findings import _walled_in
    fps = _walled_in(0.1)
    ring = fps[1]
    keep = tuple(p for p in ring.pads if not (p.box.center.x > 30.5 and abs(p.box.center.y - 30.0) < 0.1))
    assert len(keep) == len(ring.pads) - 1
    fps[1] = dc.replace(ring, pads=keep)
    fps[2] = footprint("T1", 10, 30, inst="t1", nets=("IN", "Z"))
    b = _via_only_board(fps)
    for y in (29.25, 30.75):
        b.track(Net("Z"), [Location(31.9, y), Location(34.0, y)], layer=CopperLayer.F, width=0.2, why="the gap's walls")
    plan = b.resolve()
    esc = judging(plan.occupancy)
    assert esc.judge("U9", "1") is Way.AWAY
    closed = [f for f in plan.findings if f.kind == "escape_closed"]
    assert [(f.facts["ref"], f.facts["pin"]) for f in closed] == [("U9", "1")] and "T1" in str(closed[0])


@pytest.mark.parametrize("seed", range(12))
def test_a_lane_the_first_check_finds_open_is_a_way_the_path_search_finds(seed):
    """The lanes may only find what the exact path search finds (with the same window, clearance and toward): on small
    random boards (an SOIC-8 whose pins each join a far pad, other nets' pads round it, a pour, a through-hole pad and a
    back-layer track), every pad whose lanes clear a way is cleared by `path_out` too."""
    import random
    from placemat.escapes import path_out
    from placemat.values import CopperLayer, Location, Part
    from tests.escape_fixtures import board_with, one_pad, soic8
    from tests.fixtures import footprint
    rnd = random.Random(seed)
    nets = {k: "S%d" % k for k in range(1, 9)}
    fps = [soic8(nets=nets)]
    for k in range(1, 9):
        fps.append(one_pad("T%d" % k, "t%d" % k, nets[k], 8.0 + 5.0 * k, 52.0))
    for k in range(7):
        x, y = 30.0 + rnd.uniform(-5.0, 5.0), 30.0 + rnd.uniform(-5.0, 5.0)
        if abs(x - 30.0) < 3.6 and abs(y - 30.0) < 2.9:
            x += 7.5 if x > 30.0 else -7.5                      # off the chip's own pads
        fps.append(one_pad("F%d" % k, "f%d" % k, "Z%d" % k, x, y, size=rnd.uniform(0.3, 0.9)))
    th = footprint("H1", 30.0 + rnd.choice((-1, 1)) * rnd.uniform(4.0, 5.5), 30.0 + rnd.uniform(-3.0, 3.0), w=2.6, h=1.0,
                   inst="h1", nets=("ZH", "ZH2"), through=True)
    fps.append(th)
    b = board_with(fps, keep_going=True)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    px, py = 30.0 + rnd.choice((-1, 1)) * rnd.uniform(3.5, 5.0), 30.0 + rnd.uniform(-3.0, 1.0)
    b.pour(Net("Z0"), [Location(px, py), Location(px + 1.2, py), Location(px + 1.2, py + 2.0), Location(px, py + 2.0)],
           layer=CopperLayer.F, why="another net's pour")
    ty = 30.0 + rnd.uniform(-3.0, 3.0)
    b.track(Net("ZH"), [Location(24.0, ty), Location(36.0, ty)], layer=CopperLayer.B, width=0.2, why="a back-layer track")
    occ = b.resolve().occupancy
    esc = judging(occ)
    reach = occ.settings.score_escape_reach
    checked = 0
    for number in map(str, range(1, 9)):
        found = esc.lane_check("U1", number)
        if found is None:
            continue
        toward, any_way, aim = found
        if toward:
            assert path_out(occ, "U1", number, depth=reach, toward=aim, exact=True, via_exit=False), number
            checked += 1
        if any_way:
            assert path_out(occ, "U1", number, depth=reach, exact=True, via_exit=False), number
    assert checked


def _round_pad(owner, inst, number, net, cx, cy, radius):
    """A round pad of `radius` centred at (cx, cy), its outline a 32-gon."""
    import dataclasses as dc
    from placemat.geometry import circle_polygon
    from placemat.values import Box, Location
    from tests.fixtures import pad
    outline = circle_polygon(Location(cx, cy), radius, 32)
    return dc.replace(pad(owner, inst, number, net, cx, cy, 2 * radius, 2 * radius), outlines=(outline,),
                      box=Box.of_points(outline))


def _part_of(ref, inst, pads, cx, cy):
    from placemat.board_geometry import Footprint
    from placemat.values import Box, Face, Location
    body = Box.union([p.box for p in pads])
    return Footprint(ref, inst, None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body, body, tuple(pads))


def test_a_lane_starts_at_the_round_pads_copper_not_its_box():
    """A round pad 2 mm in radius ringed by 0.1 mm pads of another net 2.3 mm from its centre, with a 15-degree gap toward
    its target: the box's corners lie past the ring, the copper's edge inside it. No lane gets out from the copper, and
    neither does the path search: the pad is no surface way out."""
    import math as m
    from placemat.escapes import path_out
    from tests.escape_fixtures import board_with, one_pad
    from placemat.values import Location, Part
    from tests.fixtures import pad
    ring = []
    k = 0
    for i in range(96):
        a = 2 * m.pi * i / 96
        if abs(m.degrees(a) - 45.0) < 7.5:
            continue
        k += 1
        ring.append(pad("Z1", "z1", k, "Z", 30 + 2.3 * m.cos(a), 30 + 2.3 * m.sin(a), 0.1, 0.1))
    fps = [_part_of("P1", "p1", [_round_pad("P1", "p1", 1, "S", 30, 30, 2.0)], 30, 30),
           _part_of("Z1", "z1", ring, 30, 30), one_pad("T1", "t1", "S", 45, 45)]
    b = board_with(fps, keep_going=True)
    for fp in fps:
        b.place(Part(fp.inst), at=Location(30, 30) if fp.ref != "T1" else Location(45, 45))
    occ = b.resolve().occupancy
    esc = judging(occ)
    toward, any_way, aim = esc.lane_check("P1", "1")
    reach = occ.settings.score_escape_reach
    assert not path_out(occ, "P1", "1", depth=reach, toward=aim, exact=True, via_exit=False)
    assert not path_out(occ, "P1", "1", depth=reach, exact=True, via_exit=False)
    assert (toward, any_way) == (False, False)
    assert esc.judge("P1", "1") is not Way.SURFACE


def _shape_board(rnd):
    """A random small board for the subset test: the pad under test (`P1`) is a large round pad, an SOIC-8 turned 45
    degrees, a rectangle pad at a random angle, one pad number on two pads apart, or a pin with its tab, among other nets' pads, a pour, a through-hole part and a back-layer
    track; every net of P1 joins a far pad."""
    import math as m
    from tests.escape_fixtures import one_pad, soic8, turned_pad
    from tests.fixtures import footprint, pad
    kind = rnd.choice(("round", "soic45", "rect", "split", "pintab"))
    if kind == "split":                 # one pad number on two copper pads apart: its centre on neither
        d = rnd.uniform(0.8, 2.5)
        main = _part_of("P1", "p1", [pad("P1", "p1", 1, "S1", 30 - d, 30, 0.6, 0.6),
                                     pad("P1", "p1", 1, "S1", 30 + d, 30, 0.6, 0.6)], 30, 30)
    elif kind == "pintab":              # a pin with its tab: one outline on the centre, one beside it
        main = _part_of("P1", "p1", [pad("P1", "p1", 1, "S1", 30, 30, 0.8, 0.8),
                                     turned_pad("P1", "p1", 1, "S1", 30 + rnd.uniform(0.3, 2.0), 30 + rnd.uniform(-1.0, 1.0),
                                                1.5, 0.6, rnd.uniform(0, 180))], 30, 30)
    elif kind == "round":
        main = _part_of("P1", "p1", [_round_pad("P1", "p1", 1, "S1", 30, 30, rnd.uniform(0.8, 2.5))], 30, 30)
    elif kind == "rect":
        main = _part_of("P1", "p1", [turned_pad("P1", "p1", 1, "S1", 30, 30, rnd.uniform(0.6, 2.5), rnd.uniform(0.3, 1.2),
                                                rnd.uniform(0, 180))], 30, 30)
    else:
        base = soic8("P1", "p1", nets={k: "S%d" % k for k in range(1, 9)})
        c, s_ = m.cos(m.radians(45)), m.sin(m.radians(45))
        pads = []
        for p in base.pads:
            x, y = p.box.center.x - 30, p.box.center.y - 30
            pads.append(turned_pad("P1", "p1", p.number, p.net, 30 + x * c - y * s_, 30 + x * s_ + y * c,
                                   p.box.width, p.box.height, 45.0))
        main = _part_of("P1", "p1", pads, 30, 30)
    nets = sorted({p.net for p in main.pads})
    extra = []
    if kind == "split":                 # each of its pads fenced close, with a narrow gap
        fence = []
        for p in main.pads:
            gap = rnd.uniform(0, 360)
            for i in range(16):
                a = 2 * m.pi * i / 16
                if abs((22.5 * i - gap + 180) % 360 - 180) > rnd.uniform(0, 12):
                    fence.append(pad("V1", "v1", len(fence) + 1, "ZV", p.box.center.x + 0.75 * m.cos(a),
                                     p.box.center.y + 0.75 * m.sin(a), 0.1, 0.1))
        extra.append(_part_of("V1", "v1", fence, 30, 30))
    fps = [main] + extra + [one_pad("T%d" % k, "t%d" % k, net, 8.0 + 5.0 * k, 52.0) for k, net in enumerate(nets)]
    reach = max(m.hypot(x - 30, y - 30) for p in main.pads for poly in p.outlines for x, y in poly)
    for k in range(9):                  # near the copper's edge, where a box's corner stands past it
        a, r = rnd.uniform(0, 2 * m.pi), rnd.uniform(0.7 * reach, reach + 1.5)
        fps.append(one_pad("F%d" % k, "f%d" % k, "Z%d" % k, 30 + r * m.cos(a), 30 + r * m.sin(a),
                           size=rnd.uniform(0.1, 0.6)))
    if True:                            # a fence of another net's pads round it, with a gap of a random width
        rr = reach + rnd.uniform(0.1, 0.6)
        n = int(2 * m.pi * rr / 0.3)
        gap, width = rnd.uniform(0, 360), rnd.uniform(5, 25)
        fence = [pad("W1", "w1", i + 1, "ZW", 30 + rr * m.cos(2 * m.pi * i / n), 30 + rr * m.sin(2 * m.pi * i / n), 0.1, 0.1)
                 for i in range(n) if abs((360.0 * i / n - gap + 180) % 360 - 180) > width / 2]
        fps.append(_part_of("W1", "w1", fence, 30, 30))
    a = rnd.uniform(0, 2 * m.pi)
    fps.append(footprint("H1", 30 + 5.5 * m.cos(a), 30 + 5.5 * m.sin(a), w=2.6, h=1.0, inst="h1", nets=("ZH", "ZH2"),
                         through=True))
    return fps


@pytest.mark.parametrize("seed", range(30))
def test_a_lane_finds_only_what_the_search_finds_on_round_turned_and_angled_pads(seed):
    import math as m
    import random
    from placemat.escapes import path_out
    from placemat.values import CopperLayer, Location, Part
    from tests.escape_fixtures import board_with
    rnd = random.Random(1000 + seed)
    fps = _shape_board(rnd)
    b = board_with(fps, keep_going=True)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    a = rnd.uniform(0, 2 * m.pi)
    px, py = 30 + 3.5 * m.cos(a), 30 + 3.5 * m.sin(a)
    b.pour(Net("Z0"), [Location(px, py), Location(px + 1.2, py), Location(px + 1.2, py + 1.5), Location(px, py + 1.5)],
           layer=CopperLayer.F, why="another net's pour")
    ty = 30.0 + rnd.uniform(-3.0, 3.0)
    b.track(Net("ZH"), [Location(24.0, ty), Location(36.0, ty)], layer=CopperLayer.B, width=0.2, why="a back-layer track")
    occ = b.resolve().occupancy
    esc = judging(occ)
    reach = occ.settings.score_escape_reach
    for number in sorted({p.number for p in fps[0].pads}):
        found = esc.lane_check("P1", number)
        if found is None:
            continue
        toward, any_way, aim = found
        if toward:
            assert path_out(occ, "P1", number, depth=reach, toward=aim, exact=True, via_exit=False), number
        if any_way:
            assert path_out(occ, "P1", number, depth=reach, exact=True, via_exit=False), number


def test_a_pad_number_whose_centre_is_on_none_of_its_copper_has_no_lanes_and_the_search_decides():
    """P1's pad 1 is two 0.6 mm pads 4 mm apart, each fenced by sixteen 0.1 mm Z pads 0.75 mm out: the centre of their
    box lies on neither. A lane from there would cross open ground; the search finds no way out of either pad."""
    import math as m
    from placemat.escapes import path_out, search_near
    from placemat.values import Location, Part
    from tests.escape_fixtures import board_with, one_pad
    from tests.fixtures import pad
    fence = []
    for cx in (28.0, 32.0):
        for i in range(16):
            a = 2 * m.pi * i / 16
            fence.append(pad("Z1", "z1", len(fence) + 1, "Z", cx + 0.75 * m.cos(a), 30 + 0.75 * m.sin(a), 0.1, 0.1))
    fps = [_part_of("P1", "p1", [pad("P1", "p1", 1, "S", 28, 30, 0.6, 0.6), pad("P1", "p1", 1, "S", 32, 30, 0.6, 0.6)],
                    30, 30),
           _part_of("Z1", "z1", fence, 30, 30), one_pad("T1", "t1", "S", 30, 10)]
    b = board_with(fps, keep_going=True)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    occ = b.resolve().occupancy
    esc = judging(occ)
    assert esc.lanes("P1", "1") == [] and esc.lane_check("P1", "1") is None
    reach = occ.settings.score_escape_reach
    near = search_near(occ)
    assert not path_out(occ, "P1", "1", depth=reach, toward=(0.0, -20.0), near=near, exact=True, via_exit=False)
    assert not path_out(occ, "P1", "1", depth=reach, near=near, exact=True, via_exit=False)
    esc.searched = 0
    assert esc.judge("P1", "1") in (Way.VIA, Way.WALLED) and esc.searched == 1


def test_the_board_s_escapes_follow_a_via_that_gives_way_and_one_put_back():
    """The cell's GND via lands on R9's back pad S and gives way to a GND via 0.95 mm off: the board's Escapes drops it and
    takes the via and tail it left, so R9's pad is judged on the board as it stands, as a fresh judgement and the path
    search judge it; and again once the via is put back as the cell drew it."""
    from placemat import giveway
    from placemat.escapes import Escapes, search_near
    from placemat.values import Cell, Near
    from tests.test_vias_give_way import _via
    from tests.fixtures import board_geometry, footprint, track
    from placemat.occupancy import Occupancy
    from placemat.layout import Board
    from placemat.values import Face, Location, Part
    vx, vy = 39.1, 41.9
    copper = [_via("GND", vx, vy, owner="m"), track("GND", 39.1, 40.0, vx, vy, w=0.2, owner="m"), _via("GND", 19.1, 22.85)]
    fps = [footprint("U1", 40, 40, w=3, h=1, inst="m.u1", nets=("GND", "X"), cell="m"),
           footprint("R9", 19.5, vy - 20, w=2, h=1, inst="r9", nets=("S", "T"), face=Face.BACK),
           footprint("T9", 8, 30, w=2, h=1, inst="t9", nets=("S", "Q"), face=Face.BACK)]
    g = board_geometry(fps, cells=["m"], copper=copper, width=50, height=50, extra_nets=("GND", "Y"))
    centre = Occupancy(g)._geometry(g.cells["m"]).reference.location
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Part("r9"), at=Location(19.5, vy - 20), face=Face.BACK)
    b.place(Part("t9"), at=Location(8, 30), face=Face.BACK)
    b.place(Cell("m"), at=Near(Location(centre.x - 20, centre.y - 20), radius=0, rotations=(0,)))
    occ = b.resolve().occupancy
    assert occ.given_way

    def held(esc):
        return {id(s) for s in esc._blockers.get(":copper", ())}

    def live():
        return {id(s) for s in occ.copper if s.kind in ("copper", "through") and s.owner not in occ.pending}

    def agrees():
        esc = occ.escapes()
        assert held(esc) == live()
        fresh = Escapes(occ, mirror=False)
        assert esc._verdict("R9", "1", esc._bans()) == fresh._verdict("R9", "1", fresh._bans(), search_near(occ))
    agrees()
    giveway.undo(occ, next(iter(occ.given_way)))
    agrees()


def test_blind_split_pad_has_only_via_spots_touching_actual_copper(monkeypatch):
    from placemat import escapes
    from placemat.occupancy import Occupancy
    from tests.fixtures import board_geometry, pad
    main = _part_of('P1', 'p1', [pad('P1', 'p1', 1, 'S', 28, 29, 0.6, 0.6),
                                pad('P1', 'p1', 1, 'S', 32, 31, 0.6, 0.6)], 30, 30)
    target = _part_of('T1', 't1', [pad('T1', 't1', 1, 'S', 10, 10, 0.6, 0.6)], 10, 10)
    occ = Occupancy(board_geometry([main, target]))
    esc = judging(occ)
    lanes, spots, _ = esc._lanes_of('P1')
    assert lanes == []
    assert spots == []  # union-box side centres stand between the two copper islands
    monkeypatch.setattr(escapes, 'path_out', lambda *a, **k: False)
    assert esc.judge('P1', '1') is Way.WALLED
    assert any(r == 'P1' and n == '1' and way is Way.WALLED for r, n, _, way, _ in esc.judged())


def test_blind_split_pad_keeps_via_spots_on_actual_annular_copper():
    from placemat.escapes import _point_poly_distance
    from placemat.occupancy import Occupancy
    from placemat.values import CopperLayer
    from tests.fixtures import board_geometry, pad
    islands = [pad('P1', 'p1', 1, 'S', 28, 30, 0.6, 0.6),
               pad('P1', 'p1', 1, 'S', 32, 30, 0.6, 0.6)]
    # Through vias reach a pad on either available copper face.
    for layers in [frozenset([CopperLayer.F]), frozenset([CopperLayer.B])]:
        parts = [dataclasses.replace(p, layers=layers) for p in islands]
        main = _part_of('P1', 'p1', parts, 30, 30)
        target = _part_of('T1', 't1', [pad('T1', 't1', 1, 'S', 10, 10, 0.6, 0.6)], 10, 10)
        esc = judging(Occupancy(board_geometry([main, target])))
        lanes, spots, _ = esc._lanes_of('P1')
        assert not lanes
        assert len(spots) == 2
        for spot in spots:
            x, y, radius = spot.circle
            assert any(_point_poly_distance((x, y), poly) <= radius + 1e-9
                       for part in parts for poly in part.outlines)
