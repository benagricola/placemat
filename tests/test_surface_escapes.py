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
    for k in ("escape_crossed", "escape_closed", "escape_walled", "escape_via"):
        assert w[k] == pytest.approx(t[k]), k


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
    assert price(Way.AWAY, s) == s.score_escape_closed and price(Way.WALLED, s) == s.score_escape_walled
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
