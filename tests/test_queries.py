"""What is at a point, what is in a box, and where a via may stand. Pure:
synthetic geometry, no KiCad."""
import dataclasses

from placemat import queries
from placemat.board_geometry import CopperItem, RuleArea
from placemat.values import Box, CopperLayer, Location
from tests.fixtures import board_geometry, footprint, rect, track

F, B = CopperLayer.F, CopperLayer.B


def _zone(net, x0, y0, x1, y1, layer=F):
    poly = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    return CopperItem("zone", net, frozenset([layer]), (poly,), Box(x0, y0, x1, y1))


def _via(net, x, y, size=0.6, drill=0.3):
    ring = rect(x, y, size, size)
    return CopperItem("via", net, frozenset([F, B]), (ring,), Box.of_points(ring), drill_mm=drill)


def _geom(copper=(), fps=(), **kw):
    g = board_geometry(list(fps), copper=list(copper), width=40, height=40,
                       extra_nets=("GND", "SIG", "V3"))
    return dataclasses.replace(g, **kw) if kw else g


def test_a_via_within_clearance_of_another_nets_track_is_blocked():
    g = _geom([track("SIG", 20, 5, 20, 35)])
    v = queries.judge_via(g, Location(20.5, 20), "GND", 0.6, 0.3)
    assert not v.clear and any("SIG" in h and "track" in h for h in v.hard)


def test_copper_of_the_vias_own_net_does_not_block():
    g = _geom([track("GND", 20, 5, 20, 35)])
    assert queries.judge_via(g, Location(20.0, 20), "GND", 0.6, 0.3).clear


def test_another_nets_pour_gives_way_rather_than_blocking():
    g = _geom([_zone("V3", 10, 10, 30, 30)])
    v = queries.judge_via(g, Location(20, 20), "GND", 0.6, 0.3)
    assert v.clear and any("V3" in s for s in v.soft)


def test_a_hole_closer_than_hole_to_hole_blocks():
    g = _geom([_via("V3", 20.5, 20)], hole_to_hole=0.25)      # a 0.2 mm web between the holes
    v = queries.judge_via(g, Location(20, 20), "V3", 0.6, 0.3)   # same net: only the hole rule applies
    assert not v.clear and any("hole" in h for h in v.hard)


def test_the_board_edge_closer_than_the_edge_clearance_blocks():
    v = queries.judge_via(_geom(), Location(0.5, 20), "GND", 0.6, 0.3)
    assert not v.clear and any("edge" in h for h in v.hard)


def test_a_rule_area_forbidding_vias_blocks_one_forbidding_tracks_does_not():
    box = ((15.0, 15.0), (25.0, 15.0), (25.0, 25.0), (15.0, 25.0))
    no_vias = RuleArea("keepout a", None, box, frozenset([F, B]), frozenset(["vias"]))
    no_tracks = RuleArea("keepout b", None, box, frozenset([F, B]), frozenset(["tracks"]))
    assert not queries.judge_via(_geom(rule_areas=(no_vias,)), Location(20, 20), "GND", 0.6, 0.3).clear
    assert queries.judge_via(_geom(rule_areas=(no_tracks,)), Location(20, 20), "GND", 0.6, 0.3).clear
