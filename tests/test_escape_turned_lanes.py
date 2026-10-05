"""board.escape(turn=Corner.X): the lanes of one escape keep track + clearance (and room for the router's grid snap) from each other and from other parts'
copper, no lane crosses another, and where a lane cannot keep clear it is a finding and its track is drawn as the lane
is, never rerouted through another lane. A 0.4 mm pitch QFN-56 (track 0.16, clearance 0.16) with a bypass part turned 135
beside pin 46 (north is -y; the west row's pad centres are at x = 26.59, its tips at 26.2575)."""
import math

import pytest

from placemat.copper import Track
from placemat.geometry import poly_distance
from placemat.values import Corner, CopperLayer, Location, Net, Part
from tests.escape_fixtures import CLEAR56, TRACK56, bypass_135, fan_board

F = CopperLayer.F
STEP = TRACK56 + CLEAR56
# turned lanes stand a track, a clearance and the router's grid snap apart (lanes.Layouter._step)
LANE_STEP = STEP + 0.1 / math.sqrt(2.0)
BYPASS_AT = (24.82, 27.86)          # pads' middle: pad 1 at (25.159, 28.199), pad 2 at (24.481, 27.521)


def _chain(plan, net):
    return [t for t in plan.copper if isinstance(t, Track) and t.net == net]


def _gap(plan, a, b):
    return min(poly_distance(x.polygon, y.polygon) for x in _chain(plan, a) for y in _chain(plan, b))


def _board(pins, order=None, bypass_at=BYPASS_AT, depth=None, pad_size=(0.56, 0.62), **kw):
    """The QFN-56 with the bypass part beside pin 46, and a NW fan of `pins` drawn."""
    cap = bypass_135("C1", "cap", ("BYP", "GND"), *bypass_at, size=pad_size)
    b = fan_board([cap], keep_going=True, **kw)
    b.place(Part("cap"), at=Location(*bypass_at))
    esc = b.escape(Part("mcu"), order or pins, turn=Corner.NW, depth=depth, why="a fan")
    for p in pins:
        b.track(Net("N%d" % p), [esc[p]], layer=F, why="its lane")
    return b, esc


def _pad_gap(plan, net, ref="C1"):
    pads = [s for s in plan.occupancy.items[ref].shapes if s.kind == "pad"]
    return min(poly_distance(t.polygon, p.poly) for t in _chain(plan, net) for p in pads)


def test_two_lanes_beside_a_turned_part_keep_the_clearance_from_it_and_from_each_other():
    b, _ = _board([44, 45])
    plan = b.resolve()
    assert [f for f in plan.findings if f.kind in ("copper", "escape_lane", "fixed")] == []
    assert _gap(plan, "N44", "N45") >= CLEAR56 - 1e-6
    for net in ("N44", "N45"):
        assert _pad_gap(plan, net) >= CLEAR56 - 1e-6, net


def test_the_lanes_of_an_escape_are_the_same_whatever_order_the_pins_are_listed_in():
    plan_a = _board([43, 44, 45])[0].resolve()
    plan_b = _board([43, 44, 45], order=[45, 43, 44])[0].resolve()
    for net in ("N43", "N44", "N45"):
        assert [(t.start, t.end) for t in _chain(plan_a, net)] == [(t.start, t.end) for t in _chain(plan_b, net)]
    assert _gap(plan_a, "N43", "N44") >= CLEAR56 - 1e-6 and _gap(plan_a, "N44", "N45") >= CLEAR56 - 1e-6


def test_risers_stagger_from_the_row_s_turn_side_end_whichever_pins_are_named():
    """A 45 moves away from its row, so it needs no lane's depth past the tips: pin 43, the row's end, has none, and each pad
    one pitch on is one stagger (the step * sqrt 2 less the pitch) further out, named or not."""
    stagger = LANE_STEP * math.sqrt(2.0) - 0.4
    for pins, expect in (([44, 45], {44: 1, 45: 2}), ([43, 44, 45], {43: 0, 44: 1, 45: 2}), ([45], {45: 2})):
        plan = _board(pins)[0].resolve()
        for pin, k in expect.items():
            riser = _chain(plan, "N%d" % pin)[0]
            assert 26.2575 - riser.end.x == pytest.approx(k * stagger, abs=3e-6), (pins, pin)


def test_the_first_lane_clears_the_pad_row_by_the_clearance_or_more():
    b, _ = _board([44, 45])
    plan = b.resolve()
    pads = [s for s in plan.occupancy.items["U1"].shapes if s.kind == "pad" and s.label != "44"]
    assert min(poly_distance(t.polygon, p.poly) for t in _chain(plan, "N44") for p in pads) >= CLEAR56 - 1e-6


def test_two_escapes_of_one_row_lay_their_lanes_parallel_a_step_apart():
    cap = bypass_135("C1", "cap", ("BYP", "GND"), 12.0, 12.0)
    b = fan_board([cap], keep_going=True)
    b.place(Part("cap"), at=Location(12.0, 12.0))
    upper = b.escape(Part("mcu"), [43, 44], turn=Corner.NW, why="the upper fan")
    lower = b.escape(Part("mcu"), [47, 48], turn=Corner.NW, why="the lower fan")
    for esc, pins in ((upper, (43, 44)), (lower, (47, 48))):
        for p in pins:
            b.track(Net("N%d" % p), [esc[p]], layer=F, why="its lane")
    plan = b.resolve()
    lines = []
    for p in (43, 44, 47, 48):
        diag = [t for t in _chain(plan, "N%d" % p) if abs(t.end.x - t.start.x) > 1e-3
                and abs(abs(t.end.x - t.start.x) - abs(t.end.y - t.start.y)) < 1e-6][0]
        lines.append(diag.start.x - diag.start.y)
    # pins 43, 44, 47, 48 are 0, 1, 4, 5 pitches from the end: each pitch is one step (0.39) across the 45s
    for line, k in zip(lines, (0, 1, 4, 5)):
        assert (lines[0] - line) / math.sqrt(2.0) == pytest.approx(k * LANE_STEP, abs=3e-6)


def test_a_lane_that_cannot_keep_clear_is_drawn_as_laid_or_not_at_all_never_rerouted_over_the_lane_beside_it():
    """The depth a lane parallel to the row needs (0.32 mm) puts the second lane on the part's pad. A track that detoured
    round the part ran over the first lane: now it is the lane as laid, or, where that runs through the part, not drawn."""
    b, esc = _board([44, 45], depth=STEP)
    plan = b.resolve()
    said = [str(f) for f in plan.findings]
    assert any(f.kind == "fixed" and "N45" in f for f in plan.findings), said
    laid = b._escape_laid[0]
    for pin in (44, 45):
        legs = _chain(plan, "N%d" % pin)
        if not legs:
            assert any("track N%d: not drawn, it would run through" % pin in t for t in said), said
            continue
        drawn = [(round(t.start.x, 6), round(t.start.y, 6)) for t in legs] + [(round(legs[-1].end.x, 6), round(legs[-1].end.y, 6))]
        assert drawn == [(round(p.x, 6), round(p.y, 6)) for p in laid.lanes[str(pin)].points]
    if _chain(plan, "N44") and _chain(plan, "N45"):
        assert _gap(plan, "N44", "N45") >= CLEAR56 - 1e-6              # never one lane on top of the other


def test_a_lane_a_hair_too_near_a_part_is_drawn_as_laid_with_findings():
    b, esc = _board([44, 45], depth=STEP, pad_size=(0.50, 0.54))
    plan = b.resolve()
    laid = b._escape_laid[0]
    legs = _chain(plan, "N45")
    drawn = [(round(t.start.x, 6), round(t.start.y, 6)) for t in legs] + [(round(legs[-1].end.x, 6), round(legs[-1].end.y, 6))]
    assert drawn == [(round(p.x, 6), round(p.y, 6)) for p in laid.lanes["45"].points]
    assert any(f.kind == "fixed" and "N45" in f for f in plan.findings)
    assert _gap(plan, "N44", "N45") >= CLEAR56 - 1e-6


def test_a_part_on_the_lane_is_a_finding_and_no_copper_is_drawn_through_it():
    b, esc = _board([44, 45], bypass_at=(25.35, 28.0))
    plan = b.resolve()
    said = [str(f) for f in plan.findings]
    assert any("track N45: not drawn, it would run through C1 pad 1" in t for t in said), said
    assert _chain(plan, "N45") == []
    assert _chain(plan, "N44") and not any("N44" in t and f.kind == "copper" for t, f in zip(said, plan.findings))


def test_lane_gaps_across_the_fan_are_a_track_a_clearance_and_the_grid_snap():
    b, _ = _board([43, 44, 45])
    plan = b.resolve()
    lines = []
    for p in (43, 44, 45):
        diag = [t for t in _chain(plan, "N%d" % p) if abs(t.end.x - t.start.x) > 1e-3
                and abs(abs(t.end.x - t.start.x) - abs(t.end.y - t.start.y)) < 1e-6][0]
        lines.append(diag.start.x - diag.start.y)
    for a, c in zip(lines, lines[1:]):
        assert (a - c) / math.sqrt(2.0) == pytest.approx(LANE_STEP, abs=3e-6)


def _seg_dist(a, b, c, d) -> float:
    """Between segments ab and cd that do not cross."""
    from placemat.geometry import point_segment_distance
    return min(point_segment_distance(a, c, d), point_segment_distance(b, c, d),
               point_segment_distance(c, a, b), point_segment_distance(d, a, b))


@pytest.mark.parametrize("pins", [[43, 44, 45], [44, 45]])
def test_turned_lane_ends_keep_the_clearance_after_the_routers_grid_snap(pins):
    """The router starts a route from a lane end at the nearest point of its grid (0.1 mm by default, each coordinate
    rounded: KRT routing_config.py GridCoord.to_grid) and runs a leg from there to the end. Wherever the board puts the
    module, in any turn, that leg keeps the clearance from the next lane."""
    from placemat.lanes import ROUTER_GRID_STEP
    g = ROUTER_GRID_STEP
    plan = _board(pins)[0].resolve()
    chains = {p: [((t.start.x, t.start.y), (t.end.x, t.end.y), t.width) for t in _chain(plan, "N%d" % p)] for p in pins}
    worst = math.inf
    for deg in range(0, 360, 15):
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        for dx, dy in ((0.0, 0.0), (0.013, 0.037), (0.05, 0.0), (0.031, 0.071), (0.077, 0.019)):
            move = lambda p: (p[0] * c - p[1] * s + dx, p[0] * s + p[1] * c + dy)
            for p in pins:
                end = move(chains[p][-1][1])
                grid = (round(end[0] / g) * g, round(end[1] / g) * g)
                w = chains[p][-1][2]
                for q in pins:
                    if q != p:
                        for a, b, wq in chains[q]:
                            worst = min(worst, _seg_dist(grid, end, move(a), move(b)) - w / 2 - wq / 2)
    assert worst >= CLEAR56 - 1e-6, worst


def test_the_snap_room_follows_the_grid_step_the_router_is_given():
    from placemat.settings import Settings
    plan = _board([43, 44, 45], settings=Settings(route_router_args=("--grid-step", "0.05")))[0].resolve()
    lines = []
    for p in (43, 44, 45):
        diag = [t for t in _chain(plan, "N%d" % p) if abs(t.end.x - t.start.x) > 1e-3
                and abs(abs(t.end.x - t.start.x) - abs(t.end.y - t.start.y)) < 1e-6][0]
        lines.append(diag.start.x - diag.start.y)
    for a, c in zip(lines, lines[1:]):
        assert (a - c) / math.sqrt(2.0) == pytest.approx(STEP + 0.05 / math.sqrt(2.0), abs=3e-6)
