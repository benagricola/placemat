"""check current-path measures a zone fill's width along the load's route:
the fill rasterised at `check.zone_step`, each cell's distance to the
fill's edge, and the widest path between the copper where the route
enters and leaves the fill. Pure: synthetic boards."""
import re

import pytest

from placemat.board_geometry import CopperItem
from placemat.checks import _Fill, current_paths, ipc2221_width_mm, kwargs_from, run_checks
from placemat.settings import Settings, bind
from placemat.values import Box, CopperLayer
from tests.fixtures import board_geometry, footprint, rect, track

F = CopperLayer.F
STEP = 0.05


def _zone(net, *outlines):
    return CopperItem("zone", net, frozenset([F]), tuple(outlines), Box.of_points([p for o in outlines for p in o]))


def _parts(amps="1A"):
    """Q1's SW pad at (11.4, 10), L1's at (18.6, 10), each 1 x 1."""
    q1 = footprint("Q1", 10, 10, nets=("GND", "SW"), fields={"Pm.I": amps})
    l1 = footprint("L1", 20, 10, nets=("SW", "VOUT"), fields={"Pm.I": amps})
    return [q1, l1]


def _sw(parts, copper, **kw):
    return {v.subject: v for v in current_paths(board_geometry(parts, copper=copper), **kw)}["SW"]


def _neck(note):
    m = re.search(r"neck at \(([-\d.]+), ([-\d.]+)\)", note)
    assert m, note
    return float(m.group(1)), float(m.group(2))


def test_a_fill_lane_between_two_carriers_is_judged_at_its_width():
    lane = rect(15, 10, 8, 1.2)                      # x 11 to 19, 1.2 mm across; both SW pads inside
    v = _sw(_parts(), [_zone("SW", lane)])
    assert v.ok is True, v.note
    assert 1.2 - STEP - 1e-6 <= v.value <= 1.2 + 1e-6
    x, y = _neck(v.note)
    assert 11.0 <= x <= 19.0 and 9.4 <= y <= 10.6
    assert "the fill's narrowest point" in v.note and "not measured" not in v.note


def test_a_fill_slit_to_a_hole_is_not_read_as_zero_and_goes_round_the_hole():
    """As KiCad stores a fill: the hole (a via's, 1 mm square) is joined to
    the outline by a slit of no width. The route goes round the hole, 1.5 mm
    either side of it."""
    fill = ((11, 8), (19, 8), (19, 12), (15, 12), (15, 10.5),                   # down the slit
            (14.5, 10.5), (14.5, 9.5), (15.5, 9.5), (15.5, 10.5), (15, 10.5),   # round the hole
            (15, 12), (11, 12))                                                  # back up the slit
    v = _sw(_parts(), [_zone("SW", fill)])
    assert v.ok is True, v.note
    assert 1.5 - STEP - 1e-6 <= v.value <= 1.5 + 1e-6


def test_a_fill_neck_narrower_than_the_need_fails_naming_its_point():
    fill = ((11, 8.5), (14.8, 8.5), (14.8, 9.8), (15.2, 9.8), (15.2, 8.5), (19, 8.5), (19, 11.5),
            (15.2, 11.5), (15.2, 10.2), (14.8, 10.2), (14.8, 11.5), (11, 11.5))   # 3 mm, a 0.4 mm neck at x 15
    v = _sw(_parts("3.6A"), [_zone("SW", fill)])
    assert v.ok is False, v.note
    assert v.limit == pytest.approx(ipc2221_width_mm(3.6, 10.0, 1.0))
    assert 0.4 - STEP - 1e-6 <= v.value <= 0.4 + 1e-6
    x, y = _neck(v.note)
    assert 14.8 - STEP <= x <= 15.2 + STEP and 9.8 <= y <= 10.2


def test_a_fill_thinner_than_one_step_reads_as_one_step_and_says_so():
    fill = ((11, 8.5), (14.8, 8.5), (14.8, 9.985), (15.2, 9.985), (15.2, 8.5), (19, 8.5), (19, 11.5),
            (15.2, 11.5), (15.2, 10.015), (14.8, 10.015), (14.8, 11.5), (11, 11.5))  # a 0.03 mm neck
    v = _sw(_parts(), [_zone("SW", fill)])
    assert v.ok is False, v.note
    assert v.value == pytest.approx(STEP)
    assert "0.05 mm step" in v.note, v.note


def test_a_route_through_a_fill_and_a_narrower_track_is_judged_by_the_track():
    """The track ends on the fill's edge; the fill beside its end is no
    narrower than the track, so the track is the neck."""
    copper = [_zone("SW", rect(13, 10, 4, 3)), track("SW", 15, 10, 18.6, 10, w=0.25)]
    v = _sw(_parts("3.6A"), copper)
    assert v.ok is False and v.value == pytest.approx(0.25), v.note
    assert "3.60 mm long neck at 0.25 mm" in v.note and "zone fill" in v.note


def test_copper_distance_reads_the_real_distance_not_zero_everywhere(monkeypatch):
    """A regression for the pure-Python `_Fill._copper_distance` (forced
    here with NativeFill off - NativeFill's own `Fill::build_copper_distance`
    has the same regression pinned in native/src/fill.rs,
    touching_reads_the_real_distance_not_zero_everywhere): a fill cell many
    millimetres from any copper must not read as distance 0 from it. A
    seed/target mix-up in the copper distance transform (the copper cells
    must be the transform's distance-0 seeds, not the other way round)
    would make every NON-copper cell - almost every query cell - read as
    distance 0 from copper however far it actually sits, since a query
    cell is itself not copper. `touching`'s own copper-box window would
    mask this for a small search radius (it never looks far enough to
    notice), so this checks `_copper_distance` directly, at a cell chosen
    far from the copper on both axes."""
    import placemat.checks as checks_module
    monkeypatch.setattr(checks_module, "_NATIVE_FILL", False)
    lane = rect(15, 10, 20, 1.2)                     # x 5..25, y 9.4..10.6
    f = _Fill(lane, STEP)
    far_right = [rect(24.5, 10, 1.0, 1.0)]           # touches the lane's own right edge
    copper_sq = f._copper_distance(far_right)
    near_left = min((c for c in range(f.nx * f.ny) if f.inside[c]), key=lambda c: f.centre(c)[0])
    assert f.centre(near_left)[0] < 6.0              # about 19 mm from far_right
    # in cells, at least (19 mm - a fill cell's own margin) / step
    assert copper_sq[near_left] > ((19.0 - 2 * STEP) / STEP) ** 2


def test_the_step_is_the_setting():
    """A coarser step reads the same 1.2 mm lane within its own step."""
    lane = rect(15, 10, 8, 1.2)
    geom = board_geometry(_parts(), copper=[_zone("SW", lane)])
    v = {v.subject: v for v in run_checks(geom, **kwargs_from(Settings(check_zone_step=0.2)))
         if v.check == "current-path"}["SW"]
    assert 1.2 - 0.2 - 1e-6 <= v.value <= 1.2 + 1e-6
    assert v.value != pytest.approx(1.15)                     # not the 0.05 mm step's reading


@pytest.mark.parametrize("plane_mm", [4.0, 2.0])
def test_a_necked_fill_is_passed_by_when_a_plane_joins_the_same_pads(plane_mm):
    """Through-hole pads on a 3 mm fill with a sliver on the front and a
    plane on the back: the load takes the plane, so the sliver is not the
    route's neck. The sliver's fill comes first in the copper, so a search
    that took the first route it found through any fill would read the
    sliver; a 2 mm plane is narrower than the front fill away from its
    sliver, so the search only finds the plane after measuring the front."""
    q1 = footprint("Q1", 10, 10, nets=("GND", "SW"), through=True, fields={"Pm.I": "1A"})
    l1 = footprint("L1", 20, 10, nets=("SW", "VOUT"), through=True, fields={"Pm.I": "1A"})
    sliver = ((11, 8.5), (14.8, 8.5), (14.8, 9.985), (15.2, 9.985), (15.2, 8.5), (19, 8.5), (19, 11.5),
              (15.2, 11.5), (15.2, 10.015), (14.8, 10.015), (14.8, 11.5), (11, 11.5))  # a 0.03 mm neck
    plane = rect(15, 10, 10, plane_mm)
    back = CopperItem("zone", "SW", frozenset([CopperLayer.B]), (plane,), Box.of_points(plane))
    v = _sw([q1, l1], [_zone("SW", sliver), back])
    assert v.ok is True, v.note
    assert plane_mm - STEP - 1e-6 <= v.value <= plane_mm + 1e-6, v.note


def test_the_route_tries_are_the_setting():
    """With one search, the route the search found first through the front
    fill is the one judged."""
    q1 = footprint("Q1", 10, 10, nets=("GND", "SW"), through=True, fields={"Pm.I": "1A"})
    l1 = footprint("L1", 20, 10, nets=("SW", "VOUT"), through=True, fields={"Pm.I": "1A"})
    sliver = ((11, 8.5), (14.8, 8.5), (14.8, 9.985), (15.2, 9.985), (15.2, 8.5), (19, 8.5), (19, 11.5),
              (15.2, 11.5), (15.2, 10.015), (14.8, 10.015), (14.8, 11.5), (11, 11.5))
    plane = rect(15, 10, 10, 2.0)
    back = CopperItem("zone", "SW", frozenset([CopperLayer.B]), (plane,), Box.of_points(plane))
    geom = board_geometry([q1, l1], copper=[_zone("SW", sliver), back])
    with bind(Settings(check_route_tries=1)):
        v = {v.subject: v for v in current_paths(geom)}["SW"]
    assert v.value == pytest.approx(STEP), v.note
