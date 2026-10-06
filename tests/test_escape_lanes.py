"""board.escape: a pin row's routes out (lanes, risers, vias), worked out when the part is placed.
The north-row model is a hand layout's arithmetic: LANE = TRACK + CLEAR; lane0 = TIP_N - LANE;
lane1 = lane0 - (lane0_track / 2 + CLEAR + VIA / 2 + SNAP); lane2 = lane1 - (VIA / 2 + CLEAR + TRACK / 2 + SNAP), SNAP the
room turned lanes leave for the router's grid snap (lanes.Layouter._step);
north is -y. Pure: synthetic boards."""
import math

import pytest

from placemat import FreeSpot
from placemat.board_geometry import NetClass
from placemat.copper import Track, Via
from placemat.lanes import ROUTER_GRID_STEP
from placemat.values import (Corner, CopperLayer, Edge, LinkWeight, Location, Near, Net, PadRef, Part,
                             Pin, X, Y)
from tests.escape_fixtures import CLEAR, DRILL, PD_NETS, TRACK, VIA, board_with, pd_board, qfn, small_part
from tests.fixtures import footprint

F = CopperLayer.F
TIP_N = 27.2
OUT_TRACK = 0.3
SNAP = ROUTER_GRID_STEP / math.sqrt(2.0)
ROW_END_W = 28.125         # the westmost north pad's outer edge: pin 32 at x = 28.25, 0.25 wide


def _hand_lanes():
    lane = OUT_TRACK + CLEAR
    lane0 = TIP_N - lane
    lane1 = lane0 - (OUT_TRACK / 2 + CLEAR + VIA / 2 + SNAP)
    lane2 = lane1 - (VIA / 2 + CLEAR + TRACK / 2 + SNAP)
    return lane0, lane1, lane2


def _north_row(board=None, **kw):
    b = board or pd_board()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], widths={32: OUT_TRACK},
                   why="VOUT, SENSE and PGOOD out of the north row", **kw)
    return b, esc


def _draw(b, esc):
    for pin, net in ((32, "VOUT"), (31, "SENSE"), (30, "PGOOD")):
        b.track(Net(net), [esc[pin]], layer=F, why="its lane")


def _lane_y(plan, net):
    """The y of the longest horizontal segment of the net's track: its lane."""
    legs = [t for t in plan.copper if isinstance(t, Track) and t.net == net and t.start.y == t.end.y]
    return max(legs, key=lambda t: abs(t.end.x - t.start.x)).start.y


def _vias(plan):
    return {v.net: v for v in plan.copper if isinstance(v, Via)}


def _gap(point, a, b, width_a, width_b=0.0):
    """Edge to edge between a track a-b (width_a) and a round (or no) end of width_b at point."""
    dx, dy = b.x - a.x, b.y - a.y
    t = max(0.0, min(1.0, ((point.x - a.x) * dx + (point.y - a.y) * dy) / (dx * dx + dy * dy)))
    return math.hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy)) - width_a / 2.0 - width_b / 2.0


def test_the_three_lanes_are_the_hand_layouts_lines():
    b, esc = _north_row()
    _draw(b, esc)
    plan = b.resolve()
    lane0, lane1, lane2 = _hand_lanes()
    assert _lane_y(plan, "VOUT") == pytest.approx(lane0, abs=1e-9)
    assert _lane_y(plan, "SENSE") == pytest.approx(lane1, abs=1e-6)       # rounded outward to the nanometre
    assert _lane_y(plan, "PGOOD") == pytest.approx(lane2, abs=1e-6)


def test_the_vias_stand_at_the_first_legal_spot_past_the_row_s_end_and_clear():
    b, esc = _north_row(chamfer=0.0)        # the hand layout's square corners
    _draw(b, esc)
    plan = b.resolve()
    vias = _vias(plan)
    lane0, lane1, lane2 = _hand_lanes()
    excite, wet = vias["SENSE"], vias["PGOOD"]
    assert excite.at.x == pytest.approx(ROW_END_W, abs=1e-6) and excite.at.y == pytest.approx(lane1, abs=1e-6)
    # the second via is the nearest spot along its lane that keeps the clearance off the first
    along = math.sqrt((VIA + CLEAR) ** 2 - (lane1 - lane2) ** 2)
    assert wet.at.y == pytest.approx(lane2, abs=1e-6)
    assert wet.at.x == pytest.approx(ROW_END_W - along, abs=2e-6)
    assert math.hypot(excite.at.x - wet.at.x, excite.at.y - wet.at.y) - VIA >= CLEAR - 1e-9
    # and each clear of the pads and of the other lanes' copper
    pads = [s for s in plan.occupancy.items["U1"].shapes if s.kind == "pad"]
    for via in (excite, wet):
        for pad in pads:
            assert pad.box.left - via.at.x > 0 or via.at.x - pad.box.right > 0 or via.at.y - pad.box.bottom > 0 or \
                pad.box.top - via.at.y > 0
        for t in (t for t in plan.copper if isinstance(t, Track) and t.net != via.net):
            assert _gap(via.at, t.start, t.end, t.width, via.size) >= CLEAR - 1e-6


def test_lanes_end_at_their_vias_and_a_lane_with_none_ends_level_with_the_outermost():
    b, esc = _north_row()
    _draw(b, esc)
    plan = b.resolve()
    vias = _vias(plan)
    west = {net: min(min(t.start.x, t.end.x) for t in plan.copper if isinstance(t, Track) and t.net == net)
            for net in ("VOUT", "SENSE", "PGOOD")}
    assert west["SENSE"] == pytest.approx(vias["SENSE"].at.x, abs=1e-6)
    assert west["PGOOD"] == pytest.approx(vias["PGOOD"].at.x, abs=1e-6)
    assert west["VOUT"] == pytest.approx(vias["PGOOD"].at.x, abs=1e-6)


def test_a_north_row_turning_east_gives_the_eastmost_pin_the_innermost_lane():
    for turn, innermost in ((Edge.WEST, 32), (Edge.EAST, 30)):
        b = pd_board()
        esc = b.escape(Part("pd"), [32, 31, 30], turn=turn, why="order")
        for pin, net in ((32, "VOUT"), (31, "SENSE"), (30, "PGOOD")):
            b.track(Net(net), [esc[pin]], layer=F, why="its lane")
        plan = b.resolve()
        by_pin = {32: "VOUT", 31: "SENSE", 30: "PGOOD"}
        ys = {pin: _lane_y(plan, net) for pin, net in by_pin.items()}
        assert max(ys, key=ys.get) == innermost                    # nearest the tips is the greatest y
        assert sorted(ys.values(), reverse=True)[0] == pytest.approx(TIP_N - (TRACK + CLEAR))


def test_without_a_turn_vias_on_a_fine_row_fall_into_a_near_and_a_far_row():
    nets = {25 + k: "S%d" % k for k in range(6)}
    b = board_with([qfn(nets=nets)], track=0.1, clearance=0.1)
    b.place(Part("pd"), at=Location(30, 30))
    esc = b.escape(Part("pd"), [25, 26, 27, 28, 29, 30], vias=[25, 26, 27, 28, 29, 30], why="south-ish vias")
    for k, pin in enumerate((25, 26, 27, 28, 29, 30)):
        b.track(Net("S%d" % k), [esc[pin]], layer=F, why="its riser")
    plan = b.resolve()
    ys = [round(_vias(plan)["S%d" % k].at.y, 6) for k in range(6)]
    assert len(set(ys)) == 2 and ys[0::2] == [ys[0]] * 3 and ys[1::2] == [ys[1]] * 3
    near, far = max(ys), min(ys)                                   # north is -y: the far row is the lower y
    assert near == pytest.approx(TIP_N - (VIA / 2 + 0.1), abs=1e-6)          # a clearance off the pin ends
    assert far < near
    vias = [_vias(plan)["S%d" % k] for k in range(6)]
    for a, c in zip(vias, vias[1:]):
        assert math.hypot(a.at.x - c.at.x, a.at.y - c.at.y) - VIA >= 0.1 - 1e-9


def test_a_lane_at_45_and_the_next_one_a_step_across_it():
    nets = {9: "A9", 10: "A10", 11: "A11"}
    b = board_with([qfn(nets=nets)])
    b.place(Part("pd"), at=Location(30, 30))
    esc = b.escape(Part("pd"), [9, 10, 11], turn=Corner.SW, why="a south row's lanes at 45")
    for pin, net in ((9, "A9"), (10, "A10"), (11, "A11")):
        b.track(Net(net), [esc[pin]], layer=F, why="its lane")
    plan = b.resolve()

    def diagonal(net):
        legs = [t for t in plan.copper if isinstance(t, Track) and t.net == net
                and t.start.x != t.end.x and t.start.y != t.end.y]
        return max(legs, key=lambda t: math.hypot(t.end.x - t.start.x, t.end.y - t.start.y))
    lines = []
    for net in ("A9", "A10", "A11"):
        t = diagonal(net)
        dx, dy = t.end.x - t.start.x, t.end.y - t.start.y
        assert abs(abs(dx) - abs(dy)) < 1e-4 and dx * dy < 0           # a south row turning west runs SW: -x, +y
        lines.append((t, (t.start.x + t.start.y)))                      # x + y is constant along it
    step = TRACK + CLEAR + SNAP
    for (_, a), (_, c) in zip(lines, lines[1:]):
        assert abs(c - a) / math.sqrt(2.0) == pytest.approx(step, abs=1e-5)


def test_a_pair_runs_a_pair_gap_apart():
    classes = {n: NetClass("pair", 0.2, 0.2, VIA, DRILL, diff_pair_width=0.2, diff_pair_gap=0.12) for n in ("P", "N")}
    b = board_with([qfn(nets={31: "P", 30: "N"})], classes=classes)
    b.place(Part("pd"), at=Location(30, 30))
    esc = b.escape(Part("pd"), [31, 30], turn=Edge.WEST, pairs=[(31, 30)], why="a pair")
    b.track(Net("P"), [esc[31]], layer=F, why="P")
    b.track(Net("N"), [esc[30]], layer=F, why="N")
    plan = b.resolve()
    assert _lane_y(plan, "P") - _lane_y(plan, "N") == pytest.approx(0.2 + 0.12, abs=1e-9)


def _cap(ref, inst, nets, cx, cy):
    return footprint(ref, cx, cy, w=3, h=1.0, inst=inst, nets=nets)


def test_a_part_linked_short_lands_clear_of_a_reserved_riser():
    def build(escape):
        fps = [qfn(nets={32: "VOUT", 31: "SENSE", 30: "PGOOD"}), _cap("C1", "c1", ("N29", "GND"), 40, 50)]
        b = board_with(fps)
        b.place(Part("pd"), at=Location(30, 30))
        esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="the lanes") if escape else None
        b.link(PadRef(Part("c1"), 1), PadRef(Part("pd"), 29), weight=LinkWeight.SHORT)
        b.place(Part("c1"))
        return b, esc
    b, esc = build(True)
    plan = b.resolve()
    laid = b._escape_laid[0]
    pads = [s for s in plan.occupancy.items["C1"].shapes if s.kind == "pad"]
    assert not any(plan.occupancy.copper_conflicts(p) for p in pads)           # clear of every lane and via
    # without the escape the same part lands where the lane would have been
    bare, _ = build(False)
    bare_plan = bare.resolve()
    bare_pads = [s for s in bare_plan.occupancy.items["C1"].shapes if s.kind == "pad"]
    lane_shapes = [s for s in plan.occupancy.copper]
    assert any(plan.occupancy._conflict(p, s, None, exact=True) for p in bare_pads for s in lane_shapes)
    assert plan.placement("c1") != bare_plan.placement("c1")


def test_a_pad_of_the_lane_s_own_net_may_stand_on_it_and_one_of_another_net_may_not():
    def run(net):
        fps = [qfn(nets={32: "VOUT", 31: "SENSE", 30: "PGOOD"}), small_part("C1", "c1", (net, "GND"), 40, 50)]
        b = board_with(fps)
        b.place(Part("pd"), at=Location(30, 30))
        b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="the lanes")
        b.place(Part("c1"), at=Pin(1, 29.25, 26.6))
        b.keep_going = True
        return b.resolve()
    assert not [f for f in run("PGOOD").findings if f.kind == "fixed"]          # pad 1 on pin 30's riser, its own net
    other = [f for f in run("GND").findings if f.kind == "fixed"]
    assert other and "PGOOD" in other[0]


def test_a_body_may_stand_over_a_lane():
    big = footprint("B1", 28.4, 26.3, w=6, h=1.0, inst="body", nets=("GND", "OTHER"))      # pads 2.4 mm either side
    b = board_with([qfn(nets={32: "VOUT", 31: "SENSE", 30: "PGOOD"}), big])
    b.place(Part("pd"), at=Location(30, 30))
    b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="the lanes")
    b.place(Part("body"), at=Location(28.4, 26.3))
    plan = b.resolve()
    assert not [f for f in plan.findings if f.kind in ("fixed", "unplaced")]
    laid = b._escape_laid[0]
    assert plan.box("body").overlaps(laid.box())


def test_a_free_spot_via_of_another_net_keeps_off_a_lane():
    def run(escape):
        b = board_with([qfn(nets={32: "VOUT", 31: "SENSE", 30: "PGOOD"})])
        b.place(Part("pd"), at=Location(30, 30))
        if escape:
            b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="the lanes")
        b.via(Net("N29"), FreeSpot(PadRef(Part("pd"), 29), radius=3.0), why="a tap from pin 29")
        return b.resolve()
    plan = run(True)
    (tap,) = [v for v in plan.copper if isinstance(v, Via) and v.net == "N29"]
    lanes = [s for s in plan.occupancy.copper if s.kind == "copper" and s.net != "N29"]
    assert lanes
    for shape in lanes:
        (x1, y1), (x2, y2) = shape.ends
        assert _gap(tap.at, Location(x1, y1), Location(x2, y2), TRACK, VIA) >= CLEAR - 1e-6
    assert not [f for f in plan.findings if f.kind == "copper"]
    free = run(False)
    (tap0,) = [v for v in free.copper if isinstance(v, Via) and v.net == "N29"]
    assert (tap.at.x, tap.at.y) != (tap0.at.x, tap0.at.y)             # the lanes moved it off the nearest spot


def test_depth_sets_the_innermost_lane_and_run_the_end_of_lanes_with_no_via():
    b = pd_board()
    esc = b.escape(Part("pd"), [32, 31], turn=Edge.WEST, depth=0.9, run=1.5, why="a deeper first lane, longer ends")
    b.track(Net("VOUT"), [esc[32]], layer=F, why="its lane")
    b.track(Net("SENSE"), [esc[31]], layer=F, why="its lane")
    plan = b.resolve()
    assert _lane_y(plan, "VOUT") == pytest.approx(TIP_N - 0.9, abs=1e-9)
    assert _lane_y(plan, "SENSE") == pytest.approx(TIP_N - 0.9 - (TRACK + CLEAR + SNAP), abs=1e-6)
    for net in ("VOUT", "SENSE"):
        west = min(min(t.start.x, t.end.x) for t in plan.copper if isinstance(t, Track) and t.net == net)
        assert west == pytest.approx(ROW_END_W - 1.5, abs=1e-6)         # run= past the row's turn-side end


def test_the_escape_has_a_step_and_its_lanes_stand_in_the_occupancy_as_copper_of_their_nets():
    b, esc = _north_row()
    _draw(b, esc)
    plan = b.resolve()
    assert "3 lanes kept for pins 32, 31, 30" in plan.step("escape U1").note
    reserved = {s.net for s in plan.occupancy.copper if s.kind == "copper"}
    assert {"VOUT", "SENSE", "PGOOD"} <= reserved
    assert not [f for f in plan.findings if f.kind in ("copper", "escape_lane")]


def test_a_west_row_turning_north_lays_its_lanes_along_y_the_same_way():
    nets = {1: "A1", 2: "A2", 3: "A3"}
    b = board_with([qfn(nets=nets)])
    b.place(Part("pd"), at=Location(30, 30))
    esc = b.escape(Part("pd"), [1, 2, 3], turn=Edge.NORTH, vias=[2], why="a west row")
    for pin, net in ((1, "A1"), (2, "A2"), (3, "A3")):
        b.track(Net(net), [esc[pin]], layer=F, why="its lane")
    plan = b.resolve()
    tip_w = 30 - 2.8

    def lane_x(net):
        legs = [t for t in plan.copper if isinstance(t, Track) and t.net == net and t.start.x == t.end.x]
        return max(legs, key=lambda t: abs(t.end.y - t.start.y)).start.x
    # pin 1 is the northmost: the innermost lane, a track and a clearance out from the tips (west is -x)
    assert lane_x("A1") == pytest.approx(tip_w - (TRACK + CLEAR), abs=1e-9)
    assert lane_x("A2") == pytest.approx(tip_w - (TRACK + CLEAR) - (VIA / 2 + CLEAR + TRACK / 2 + SNAP), abs=1e-6)
    assert lane_x("A3") == pytest.approx(lane_x("A2") - (VIA / 2 + CLEAR + TRACK / 2 + SNAP), abs=1e-6)


def test_a_part_turned_a_quarter_lays_the_row_it_now_has():
    """The part's north row, once the part is turned 90, faces west: the lanes follow the row."""
    b = board_with([qfn(nets={32: "VOUT", 31: "SENSE", 30: "PGOOD"})])
    b.place(Part("pd"), at=Location(30, 30), rotation=90.0)
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.SOUTH, why="the turned row")      # pin 32 is its southmost
    for pin, net in ((32, "VOUT"), (31, "SENSE"), (30, "PGOOD")):
        b.track(Net(net), [esc[pin]], layer=F, why="its lane")
    plan = b.resolve()
    pad = plan.occupancy.pad_location("U1", "32")
    legs = [t for t in plan.copper if isinstance(t, Track) and t.net == "VOUT"]
    assert (legs[0].start.x, legs[0].start.y) == pytest.approx((pad.x, pad.y))
    lane = max((t for t in legs if t.start.x == t.end.x), key=lambda t: abs(t.end.y - t.start.y))
    assert lane.start.x == pytest.approx(30 - 2.8 - (TRACK + CLEAR), abs=1e-9)           # the innermost lane, west of the tips
    assert not [f for f in plan.findings if f.kind in ("copper", "escape_lane")]


def test_a_firm_part_placed_at_a_lane_end_rides_the_searched_part_whose_lane_it_is():
    b = board_with([qfn(nets=PD_NETS), small_part("C1", "c_pd", ("VOUT", "GND"))])
    b.place(Part("pd"), at=Near(Location(30, 30), radius=0.5, step=0.5, rotations=(0.0,)))
    esc = b.escape(Part("pd"), [32], turn=Edge.WEST, why="one lane")
    b.place(Part("c_pd"), at=Pin(1, X(esc[32].end), Y(esc[32].end)), rotation=90.0, why="at the lane's end")
    plan = b.resolve()
    end = b._escape_laid[0].lanes["32"].end
    pad = plan.occupancy.pad_location("C1", "1")
    assert (pad.x, pad.y) == pytest.approx((end.x, end.y), abs=1e-6)
    assert "rides pd" in plan.step("c_pd").note


# ---------------------------------------------------------------- the chamfer of a lane's corner
def _clear_of_vias(plan):
    """The least edge-to-edge gap from any lane track to a via of another net."""
    tracks = [t for t in plan.copper if isinstance(t, Track)]
    vias = [v for v in plan.copper if isinstance(v, Via)]
    return min(_gap(v.at, t.start, t.end, t.width, v.size) for v in vias for t in tracks if t.net != v.net)


def _diagonals(plan, net):
    return [t for t in plan.copper if isinstance(t, Track) and t.net == net and t.start.x != t.end.x and t.start.y != t.end.y]


def test_an_outer_lane_s_chamfer_is_judged_against_an_inner_lane_s_via_where_the_via_is_searched():
    """A chamfer runs across the inside of the turn, nearer an inner lane's via than the square corner is."""
    b = pd_board(via_size=0.8, clearance=0.15)
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="a wide via beside a 45")
    _draw(b, esc)
    plan = b.resolve()
    assert _clear_of_vias(plan) >= 0.15 - 1e-6
    assert not [f for f in plan.findings if f.kind in ("copper", "escape_lane")], plan.findings


def test_a_square_cornered_escape_judges_its_lanes_square():
    b = pd_board(via_size=0.8, clearance=0.15)
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], chamfer=0.0, why="square")
    _draw(b, esc)
    plan = b.resolve()
    assert not _diagonals(plan, "PGOOD")
    assert _clear_of_vias(plan) >= 0.15 - 1e-6
    assert not [f for f in plan.findings if f.kind in ("copper", "escape_lane")]


def test_a_track_that_begins_with_a_lane_is_drawn_with_the_escape_s_chamfer():
    b = pd_board()                              # copper.chamfer is 1.0
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], chamfer=0.1, why="a small cut")
    _draw(b, esc)
    plan = b.resolve()
    (cut,) = _diagonals(plan, "PGOOD")
    assert math.hypot(cut.end.x - cut.start.x, cut.end.y - cut.start.y) == pytest.approx(0.1 * math.sqrt(2.0), abs=1e-5)
    assert not [f for f in plan.findings if f.kind in ("copper", "escape_lane")]


def test_the_escape_s_chamfer_defaults_to_the_copper_chamfer():
    b = pd_board()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="the default")
    assert b._escapes[esc.index].chamfer == b.settings.copper_chamfer


def test_a_track_s_own_chamfer_is_drawn_as_given():
    b = pd_board()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], chamfer=0.5, why="a big cut")
    b.track(Net("VOUT"), [esc[32]], layer=F, why="its lane")
    b.track(Net("SENSE"), [esc[31]], layer=F, why="its lane")
    b.track(Net("PGOOD"), [esc[30]], layer=F, chamfer=0.1, why="a smaller cut than the escape's")
    plan = b.resolve()
    (cut,) = _diagonals(plan, "PGOOD")
    assert math.hypot(cut.end.x - cut.start.x, cut.end.y - cut.start.y) == pytest.approx(0.1 * math.sqrt(2.0), abs=1e-5)


def test_a_lane_is_laid_out_with_the_chamfer_its_track_says():
    """The vias are searched against the corner a lane's track will draw, not the escape's."""
    def run(track_chamfer):
        b = pd_board(via_size=0.8, clearance=0.15)
        esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], why="a wide via beside a 45")
        b.track(Net("VOUT"), [esc[32]], layer=F, why="its lane")
        b.track(Net("SENSE"), [esc[31]], layer=F, why="its lane")
        b.track(Net("PGOOD"), [esc[30]], layer=F, chamfer=track_chamfer, why="its lane")
        plan = b.resolve()
        assert not [f for f in plan.findings if f.kind in ("copper", "escape_lane")], plan.findings
        return _vias(plan)["SENSE"].at.x
    assert run(0.1) > run(None) + 1e-3          # a small cut leaves the via where the square corner allows


def test_a_reservation_is_replaced_by_the_copper_drawn_in_its_place():
    """A track that draws a lane thinner than it was reserved: copper planned beside it is judged against
    the drawn track."""
    spot = Location(30.0, TIP_N - 1.5 - 0.5)            # 0.5 off the lane's centreline: clear of 0.1 wide, not of 0.2

    def run(width):
        b = pd_board()
        esc = b.escape(Part("pd"), [25], turn=Edge.WEST, vias=[25], depth=1.5, why="one lane, high")
        b.track(Net("N25"), [esc[25]], layer=F, width=width, why="its lane")
        b.via(Net("N5"), spot, why="a via beside the lane")
        plan = b.resolve()
        held = [s for s in plan.occupancy.copper if s.kind == "copper" and s.net == "N25"]
        assert len(held) == len([t for t in plan.copper if isinstance(t, Track) and t.net == "N25"])
        return [str(f) for f in plan.findings if f.kind == "copper"]
    assert run(None)
    assert not run(0.1), run(0.1)


# ----------------------------------------------------------------- the lanes' vias
def test_via_size_and_via_drill_size_the_lanes_vias_and_their_steps():
    size, drill = 0.5, 0.25
    b = pd_board()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], widths={32: OUT_TRACK}, chamfer=0.0,
                   via_size=size, via_drill=drill, why="smaller vias than the board's")
    _draw(b, esc)
    plan = b.resolve()
    vias = _vias(plan)
    assert {(v.size, v.drill) for v in vias.values()} == {(size, drill)}
    lane0 = TIP_N - (OUT_TRACK + CLEAR)
    lane1 = lane0 - (OUT_TRACK / 2 + CLEAR + size / 2 + SNAP)
    assert _lane_y(plan, "SENSE") == pytest.approx(lane1, abs=1e-6)
    assert not [f for f in plan.findings if f.kind in ("copper", "escape_lane")]


def test_the_lanes_vias_default_to_the_boards():
    b = pd_board()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31], why="the default")
    decl = b._escapes[esc.index]
    assert (decl.via_size, decl.via_drill) == (b.via_size, b.via_drill)
