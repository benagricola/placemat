"""A track leg whose ends differ by less than `copper.straight_tolerance` on one
axis is one straight segment, not a straight plus a sub-micron jog; `measure
--copper` judges 0/45/90 with the same tolerance. Pure: synthetic boards."""

from placemat.copper import octilinear
from placemat.describe import copper_segments
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import CopperLayer, Location, Net
from tests.fixtures import board_geometry, footprint, track


def _legs(points, **kw):
    return octilinear([Location(*p) for p in points], **kw)


def test_a_leg_a_micron_off_axis_is_one_straight_segment():
    pts = _legs([(10.0, 20.0), (30.0, 20.001)], tolerance=0.002)
    assert len(pts) == 2


def test_a_leg_ten_microns_off_axis_still_takes_its_jog():
    pts = _legs([(10.0, 20.0), (30.0, 20.01)], tolerance=0.002)
    assert len(pts) == 3


def test_the_tolerance_defaults_to_a_nanometre():
    assert len(_legs([(10.0, 20.0), (30.0, 20.001)])) == 3


def test_the_setting_defaults_to_two_microns():
    assert Settings().copper_straight_tolerance == 0.002


def _board(**kw):
    g = board_geometry([footprint("U1", 10, 10, w=4, h=2, inst="u1", nets=("A", "B")),
                        footprint("U2", 30, 10.001, w=4, h=2, inst="u2", nets=("A", "B"))], width=60, height=60)
    return Board(g, edge_margin=1.0, settings=Settings(**kw))


def _tracks(**kw):
    from placemat.values import PadRef, Part
    b = _board(**kw)
    b.track(Net("B"), [PadRef(Part("u1"), 2), PadRef(Part("u2"), 1)], layer=CopperLayer.F, chamfer=0)
    return [op for op in b.resolve().copper if type(op).__name__ == "Track"]


def test_a_pad_to_pad_track_a_micron_off_axis_is_one_segment():
    assert len(_tracks()) == 1


def test_the_setting_is_what_decides_it():
    assert len(_tracks(copper_straight_tolerance=0.0005)) == 2


def test_measure_copper_does_not_flag_a_micron_off_axis_leg():
    leg = track("A", 8.6, 10.0, 9.1, 10.001)
    g = board_geometry([footprint("U1", 10, 10, inst="u1")], copper=[leg], width=40, height=30)
    (seg,) = copper_segments(g, [], tolerance=0.002)
    assert seg["octilinear"]
    (seg,) = copper_segments(g, [], tolerance=0.0005)
    assert not seg["octilinear"]


def test_measure_copper_still_flags_a_ten_micron_leg():
    leg = track("A", 8.6, 10.0, 10.6, 10.01)
    g = board_geometry([footprint("U1", 10, 10, inst="u1")], copper=[leg], width=40, height=30)
    (seg,) = copper_segments(g, [], tolerance=0.002)
    assert not seg["octilinear"]
