"""board.escape(vias=) at a fine pitch: a 0.4 mm pitch QFN-56 (track 0.16, clearance 0.16) whose south row's pins 9 and 10
both end in a 0.45 / 0.20 via. Two such vias on neighbouring axes cannot both stand on their own, straight lanes: a via
needs 0.465 mm between its middle and a lane beside it, and the pitch is 0.4. The later lane jogs away at 45 past the first
via and ends off its own axis. South is +y; the row's pad tips are at y = 33.7425, pin 9 is at x = 30.6, pin 10 at 31.0."""
import math

import pytest

from placemat.copper import Track, Via
from placemat.geometry import point_segment_distance, poly_distance
from placemat.values import CopperLayer, Location, Net, Part
from tests.conftest import needs_kicad
from tests.escape_fixtures import CLEAR56, TRACK56, fan_board

F = CopperLayer.F
TIPS = 33.7425
VIA, DRILL = 0.45, 0.20


def _plan(pins, vias, via_size=VIA, via_drill=DRILL, **kw):
    b = fan_board(keep_going=True, via_size=via_size, via_drill=via_drill)
    esc = b.escape(Part("mcu"), pins, vias=vias, why="south pins", **kw)
    for p in pins:
        b.track(Net("N%d" % p), [esc[p]], layer=F, why="its lane")
    return b, b.resolve()


def _vias(plan):
    return {v.net: v for v in plan.copper if isinstance(v, Via)}


def _tracks(plan, net):
    return [t for t in plan.copper if isinstance(t, Track) and t.net == net]


def _via_to_track(via, track):
    return point_segment_distance((via.at.x, via.at.y), (track.start.x, track.start.y), (track.end.x, track.end.y)) \
        - via.size / 2.0 - track.width / 2.0


def test_two_vias_on_neighbouring_fine_pins_keep_every_clearance_among_themselves_and_the_pads():
    b, plan = _plan([9, 10], [9, 10])
    vias = _vias(plan)
    assert set(vias) == {"N9", "N10"}
    assert [f for f in plan.findings if f.kind in ("copper", "escape_lane", "fixed", "escape")] == []
    a, c = vias["N9"], vias["N10"]
    centres = math.hypot(a.at.x - c.at.x, a.at.y - c.at.y)
    assert centres - VIA >= CLEAR56 - 1e-6                                          # copper to copper
    assert centres - DRILL >= b.geometry.hole_to_hole + (0.0) - 1e-6                # hole to hole
    for via, other in ((a, "N10"), (c, "N9")):
        for t in _tracks(plan, other):
            assert _via_to_track(via, t) >= CLEAR56 - 1e-6, (via.net, t)
    for via in (a, c):
        for fp in plan.geometry.footprints:
            for p in fp.pads:
                if p.net == via.net:
                    continue
                ring = p.outlines[0]
                gap = min(point_segment_distance((via.at.x, via.at.y), q, r)
                          for q, r in zip(ring, tuple(ring[1:]) + (ring[0],))) - VIA / 2.0
                assert gap >= CLEAR56 - 1e-6, (via.net, p.number)


def test_the_two_lanes_keep_a_clearance_from_each_other_and_from_the_vias_they_pass():
    _, plan = _plan([9, 10], [9, 10])
    for x, y in (("N9", "N10"), ("N10", "N9")):
        gap = min(poly_distance(t.polygon, u.polygon) for t in _tracks(plan, x) for u in _tracks(plan, y))
        assert gap >= CLEAR56 - 1e-6
    vias = _vias(plan)
    for via in vias.values():
        for t in _tracks(plan, "N10" if via.net == "N9" else "N9"):
            assert _via_to_track(via, t) >= CLEAR56 - 1e-6


def test_the_first_via_stands_straight_out_of_its_pin_as_near_as_its_own_pad_lets_it():
    _, plan = _plan([9, 10], [9, 10])
    first = _vias(plan)["N9"]
    assert first.at.x == pytest.approx(30.6, abs=1e-6)
    assert first.at.y == pytest.approx(TIPS + VIA / 2.0 + CLEAR56, abs=1e-5)


def test_the_second_lane_jogs_at_45_away_from_the_first_and_ends_at_its_via():
    _, plan = _plan([9, 10], [9, 10])
    second = _vias(plan)["N10"]
    legs = _tracks(plan, "N10")
    assert len(legs) == 2
    riser, diag = legs
    assert riser.start.x == riser.end.x == pytest.approx(31.0, abs=1e-6)
    assert abs(abs(diag.end.x - diag.start.x) - abs(diag.end.y - diag.start.y)) < 1e-4       # a 45, to the nanometre
    assert diag.end.x > diag.start.x                                                         # away from pin 9
    assert (second.at.x, second.at.y) == (diag.end.x, diag.end.y)


def test_a_via_alone_is_not_pushed_out_by_the_stub_of_the_pin_beside_it():
    """The lane of pin 10, which has no via, is a stub a track and a clearance long: pin 9's via clears its end."""
    _, plan = _plan([9, 10], [9])
    via = _vias(plan)["N9"]
    stub_end = TIPS + TRACK56 + CLEAR56
    assert via.at.y < stub_end + 0.5
    assert math.hypot(via.at.x - 31.0, via.at.y - stub_end) - VIA / 2.0 - TRACK56 / 2.0 >= CLEAR56 - 1e-6


def test_a_lane_that_cannot_clear_what_stands_beside_it_says_what_blocks_it_and_how_far_off():
    """The default 0.6 mm via at 0.4 mm pitch: the message names the lane or via in the way, not the pad the
    search started at, and its numbers are the true ones."""
    with pytest.raises(ValueError) as e:
        _plan([9, 10], [9, 10], via_size=0.9, via_drill=0.3)
    said = str(e.value)
    assert "pin 10's via has no legal spot" in said
    assert "pad 9 of its own part" not in said, said


@needs_kicad
def test_kicads_drc_passes_the_two_vias_and_their_lanes(tmp_path):
    from tests.test_escape_lanes_drc import _violations
    _, plan = _plan([9, 10], [9, 10])
    assert len([v for v in plan.copper if isinstance(v, Via)]) == 2
    assert _violations(tmp_path, plan, "fine_vias", clearance=CLEAR56) == []
