"""A copper finding measures a straight track as KiCad's DRC does: the
SHAPE_SEGMENT it is, its centreline and half its width
(shape_collisions.cpp, Collide( SHAPE_SEGMENT, SHAPE_SEGMENT ) and
Collide( SHAPE_LINE_CHAIN_BASE, SHAPE_SEGMENT )), not the track's polygon,
whose round ends stand a little outside the copper so placement never
reads it smaller than it is."""
import dataclasses
import math

from placemat.board_geometry import CopperItem
from placemat.copper import Track
from placemat.layout import _shape_of
from placemat.occupancy import Occupancy, Shape
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Face, Location
from tests.fixtures import board_geometry, footprint

RULE = 0.16
W = 0.16
FRONT = frozenset([Face.FRONT])
TOP = frozenset([CopperLayer.F])


def _occ(copper=()):
    g = board_geometry([footprint("U1", 30, 30)], copper=copper, width=40, height=40, clearance=RULE)
    return Occupancy(g, edge_margin=0.0, settings=Settings())


def _corner_tracks(dy=0.2):
    """Two tracks whose round ends face each other on a diagonal: the gap is
    hypot(0.25, dy) - W, where the end caps' polygons stand furthest out."""
    a = Track("N1", CopperLayer.F, W, Location(10.25, 10.0 + dy), Location(10.25, 10.025 + dy))
    b = Track("N2", CopperLayer.F, W, Location(10.0, 10.0), Location(10.0, 6.7))
    return a, b


def test_two_track_ends_a_hair_over_the_rule_are_clear():
    a, b = _corner_tracks()
    assert math.hypot(0.25, 0.2) - W > RULE                      # 0.16016 mm
    assert _occ()._conflict(_shape_of(a), _shape_of(b), None, exact=True, check=True) is None


def test_two_track_ends_short_of_the_rule_by_more_than_the_epsilon_are_found():
    a, b = _corner_tracks(dy=0.1985)                             # 0.15895 mm
    why = _occ()._conflict(_shape_of(a), _shape_of(b), None, exact=True, check=True)
    assert why is not None
    assert abs(why.facts["gap_mm"] - (math.hypot(0.25, 0.1985) - W)) < 2e-6


def test_a_track_end_and_a_pad_are_measured_from_the_track_centreline():
    a, _ = _corner_tracks()
    x, y = 10.25 - 0.08 - RULE - 0.0003, 10.2       # the pad's corner on the track end's axis, 0.3 um short
    pad = ((x - 1.0, y - 0.5), (x, y - 0.5), (x, y + 0.5), (x - 1.0, y + 0.5))
    o = Shape("P1", "pad", FRONT, TOP, "N2", pad, Box.of_points(pad))
    assert _occ()._conflict(_shape_of(a), o, None, exact=True, check=True) is None


def test_a_read_track_is_measured_as_its_segment_too():
    """A track read from the board (its outline KiCad's, grown by the arc
    error) against a planned one."""
    a, b = _corner_tracks()
    read = CopperItem("track", "N2", TOP, (b.polygon,), b.box, None, W,
                      anchors=((b.start.x, b.start.y), (b.end.x, b.end.y)), length_mm=b.length)
    occ = _occ(copper=[read])
    assert occ.copper_conflicts(_shape_of(a), check=True) == []
    near = dataclasses.replace(a, start=Location(10.25, 10.19), end=Location(10.25, 10.215))
    assert occ.copper_conflicts(_shape_of(near), check=True) != []


def test_a_via_off_a_pours_corner_is_measured_from_its_round_stroke():
    """A pour is drawn as a filled polygon with a stroke: KiCad collides its
    outline and a segment of the stroke's width along each edge
    (EDA_SHAPE::MakeEffectiveShapes), so the stroke rounds each corner where
    the pour's grown polygon has a mitre."""
    from placemat.copper import Pour, Via
    pour = Pour("N2", CopperLayer.F, ((0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0)), stroke=0.2)
    reach = 0.1 + 0.3 + RULE + 0.0003                    # half the stroke, the via's radius, the rule, 0.3 um over
    at = 5.0 + reach / math.sqrt(2.0)
    via = Via("N1", Location(at, at), 0.3, 0.6)
    occ = _occ()
    assert occ._conflict(_shape_of(via), _shape_of(pour), None, exact=True, check=True) is None
    near = Via("N1", Location(at - 0.001, at - 0.001), 0.3, 0.6)
    assert occ._conflict(_shape_of(near), _shape_of(pour), None, exact=True, check=True) is not None
