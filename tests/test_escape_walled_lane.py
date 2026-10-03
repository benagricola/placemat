"""A pin whose escape lane (board.escape) ends against another part's pad is walled off: the lane is the way out, so the way
on is looked for from where it ends, among the copper the clearance check would refuse. The part's own net has a second
pad elsewhere, so the pin is not a handoff. The lane of pin 50 of the QFN-56 runs straight west and ends at x 25.94; a
pocket of three pads of one other net (a pad above and one below the lane, a clearance off it, and one across its end)
leaves no room for a track beyond it."""
import dataclasses

from placemat.board_geometry import Footprint
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Face, Location, Net, Part
from tests.escape_fixtures import fan_board, one_pad
from tests.fixtures import pad

F = CopperLayer.F
LANE_Y, LANE_END = 30.2, 25.9375
HALF = 0.08 + 0.16                   # a track's half width and its clearance


def _pocket(face=Face.FRONT, through=True, end_gap=0.4, size=2.0, side=HALF, end=True):
    """J1: three pads of net VB, `size` mm square, the lane's pocket: one above the lane (its edge `side` off the lane's
    axis), one below, and, unless `end` is off, one `end_gap` past the lane's end."""
    spots = [(25.0, LANE_Y - side - size / 2), (25.0, LANE_Y + side + size / 2)]
    if end:
        spots.append((LANE_END - end_gap - size / 2, LANE_Y))
    pads = tuple(pad("J1", "j1", k, "VB", x, y, size, size, through=through, face=face) for k, (x, y) in enumerate(spots, 1))
    body = Box.union([p.box for p in pads])
    return Footprint("J1", "j1", None, "J1", Location(25.0, LANE_Y), 0.0, face, body, body.inflate(0.1), body, pads)


def _plug(drill):
    """J2: an unplated hole of `drill` mm across the lane's end, its edge 0.4 mm past it."""
    at = Location(LANE_END - 0.4 - drill / 2, LANE_Y)
    body = Box(at.x - drill / 2, at.y - drill / 2, at.x + drill / 2, at.y + drill / 2)
    return Footprint("J2", "j2", None, "J2", at, 0.0, Face.FRONT, body, body.inflate(0.1), body, (), npth=((at, drill),))


def _ban(box):
    from placemat.board_geometry import RuleArea
    from placemat.geometry import box_polygon
    return RuleArea("keepout vias [*.Cu]_1", None, box_polygon(box), frozenset(), frozenset(["vias"]))


def _board(blocker, track=False, plug=None, areas=()):
    far = one_pad("X1", "x1", "N50", 50.0, 50.0)
    g = one_pad("G1", "g1", "GND", 10.0, 10.0)
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False)
    b = fan_board([far, g, *[p for p in (blocker, plug) if p]], exposed=True, keep_going=True, settings=cfg)
    b.geometry = dataclasses.replace(b.geometry, rule_areas=tuple(areas))
    if plug:
        b.place(Part("j2"), at=plug.location)
    b.place(Part("g1"), at=Location(10.0, 10.0))
    b.place(Part("x1"), at=Location(50.0, 50.0))
    if blocker:
        b.place(Part("j1"), at=blocker.location, face=blocker.face)
    esc = b.escape(Part("mcu"), [50], why="pin 50 out")
    if track:
        b.track(Net("N50"), [esc[50]], layer=F, why="its stub")
    return b


def _walled(plan):
    return [str(f) for f in plan.findings if f.kind == "escape_walled" and str(f).startswith("U1 pin 50 ")]


def test_a_lane_that_ends_in_a_pocket_of_through_hole_pads_is_walled_off_and_names_them():
    assert _walled(_board(_pocket()).resolve()) == ["U1 pin 50 (N50): walled off by J1"]


def test_a_lane_whose_stub_is_drawn_is_walled_off_the_same():
    assert _walled(_board(_pocket(), track=True).resolve()) == ["U1 pin 50 (N50): walled off by J1"]


def test_the_same_pocket_of_pads_on_the_far_face_leaves_the_lane_its_way_out():
    assert _walled(_board(_pocket(face=Face.BACK, through=False)).resolve()) == []


def test_a_lane_with_room_beyond_its_end_is_no_finding():
    assert _walled(_board(None).resolve()) == []
    assert _walled(_board(_pocket(end_gap=3.0, size=0.5)).resolve()) == []


def test_an_unplated_hole_across_the_lanes_end_walls_it_like_a_pad():
    pocket = _pocket(end=False)
    assert _walled(_board(pocket).resolve()) == []
    assert _walled(_board(pocket, plug=_plug(2.0)).resolve()) == ["U1 pin 50 (N50): walled off by J1, J2"]


def _with_via_exit(b):
    b.settings = dataclasses.replace(b.settings, place_escape_lane_via_exit=True)
    return b


def test_a_lane_whose_only_way_on_is_a_via_spot_is_walled_off_unless_the_setting_counts_the_via():
    cavity = _pocket(side=0.8, end_gap=1.3)
    (found,) = _walled(_board(cavity).resolve())
    assert found == "U1 pin 50 (N50): walled off by J1"
    assert _walled(_with_via_exit(_board(cavity)).resolve()) == []


def test_a_pad_with_no_lane_keeps_the_via_rule():
    far = one_pad("X1", "x1", "N50", 50.0, 50.0)
    g = one_pad("G1", "g1", "GND", 10.0, 10.0)
    b = fan_board([far, g, _pocket(side=0.8, end_gap=1.3)], exposed=True, keep_going=True,
                  settings=dataclasses.replace(Settings(), cleanup_enabled=False))
    b.place(Part("g1"), at=Location(10.0, 10.0))
    b.place(Part("x1"), at=Location(50.0, 50.0))
    b.place(Part("j1"), at=_pocket().location)
    assert _walled(b.resolve()) == []


def test_a_via_ban_over_the_cavity_walls_the_lane_with_the_setting_on_too():
    cavity = _pocket(side=0.8, end_gap=1.3)
    ban = _ban(Box(24.6, 29.0, 26.0, 31.4))
    (found,) = _walled(_with_via_exit(_board(cavity, areas=[ban])).resolve())
    assert found.startswith("U1 pin 50 (N50): walled off by J1")
