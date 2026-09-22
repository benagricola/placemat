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


def test_a_tail_crossing_another_nets_track_on_its_layer_is_blocked():
    g = _geom([track("SIG", 20, 5, 20, 35)])
    said = queries.judge_tail(g, Location(15, 20), Location(25, 20), "GND", 0.2, F)
    assert said and "SIG" in said[0]
    assert queries.judge_tail(g, Location(15, 20), Location(25, 20), "GND", 0.2, B) == ()


def test_the_search_returns_the_nearest_clear_spot_and_a_tally_of_the_rest():
    blocked = lambda c: ("copper", ()) if c.x < 20.9 else (None, ())
    spot, tally, tried = queries.free_spot(Location(20, 20), blocked, radius=2.0, step=0.1)
    assert spot is not None and spot.at.x >= 20.9
    assert tally["copper"] >= 1 and tried > tally["copper"]


def test_the_search_is_identical_run_twice():
    judge = lambda c: ("edge", ()) if (c.x + c.y) % 0.7 < 0.3 else (None, ())
    a = queries.free_spot(Location(20, 20), judge, radius=1.0, step=0.1)
    b = queries.free_spot(Location(20, 20), judge, radius=1.0, step=0.1)
    assert a[0] == b[0] and a[1] == b[1]


def test_nowhere_within_the_radius_returns_no_spot_and_the_whole_tally():
    spot, tally, tried = queries.free_spot(Location(20, 20), lambda c: ("edge", ()), radius=0.5, step=0.1)
    assert spot is None and tally["edge"] == tried


def test_a_real_search_clears_a_blocking_track():
    g = _geom([track("SIG", 20.5, 5, 20.5, 35, w=0.3)])
    judge = queries.via_judge(g, Location(20, 20), "GND", 0.6, 0.3, 0.2, F)
    spot, tally, _ = queries.free_spot(Location(20, 20), judge, radius=3.0, step=0.1)
    assert spot is not None
    assert queries.judge_via(g, spot.at, "GND", 0.6, 0.3).clear
    assert tally                                # the nearer spots failed, and it says why


def test_a_net_named_like_an_obstacle_is_tallied_by_what_it_is():
    """A reason is bucketed by its shape, not by the first word that looks
    like a kind: a track of a net called /mcu/edge_led is copper, not the edge."""
    assert queries._kind("0.12 mm from /mcu/edge_led track on F.Cu (needs 0.20)") == "track"
    assert queries._kind("0.30 mm from hole_sense via on B.Cu/F.Cu (needs 0.20)") == "via"
    assert queries._kind("0.20 mm from the board edge (needs 0.50)") == "edge"
    assert queries._kind("off the board") == "edge"
    assert queries._kind("hole 0.10 mm from the via GND hole (needs 0.25)") == "hole"
    assert queries._kind("tail 0.05 mm from tail_en track on F.Cu (needs 0.20)") == "tail"
    assert queries._kind("inside keepout a, which forbids vias") == "keepout"


def test_the_copper_under_a_point_is_named_per_layer():
    g = _geom([_zone("GND", 0, 0, 40, 40, layer=B), track("SIG", 20, 5, 20, 35)])
    at = queries.copper_at(g, Location(20, 20))
    assert [c.net for c in at[F]] == ["SIG"] and [c.net for c in at[B]] == ["GND"]


def test_the_copper_in_a_box_is_counted_by_net_and_kind():
    g = _geom([track("SIG", 20, 5, 20, 35), track("SIG", 22, 5, 22, 35), _via("GND", 21, 20)])
    got = queries.copper_in(g, Box(18, 18, 24, 22))
    assert got[F][("SIG", "track")] == 2 and got[F][("GND", "via")] == 1


def test_the_nearest_copper_of_another_net_is_measured_to_its_edge():
    g = _geom([track("SIG", 20, 5, 20, 35, w=0.3), track("GND", 21.5, 5, 21.5, 35)])
    d = queries.nearest_foreign(g, Location(21, 20), F, "GND")
    assert abs(d - 0.85) < 1e-6                 # to SIG's edge at 20.15; GND is its own net
    assert queries.nearest_foreign(g, Location(21, 20), B, "GND") is None


def test_a_tail_may_not_cross_a_neighbouring_pin_of_the_same_part():
    """The source pad is the via's own net and so already exempt. Exempting
    its whole part let a tail run over the pin beside it on another net."""
    u = footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("GND", "SIG"))    # pads at 18.6 and 21.4
    g = _geom(fps=[u])
    gnd = next(p for p in u.pads if p.net == "GND")
    past_sig = Location(23.0, 20.0)                     # straight across the SIG pad
    judge = queries.via_judge(g, gnd.box.center, "GND", 0.6, 0.3, 0.2, F)
    why, _ = judge(past_sig)
    assert why is not None and "SIG" in why


def test_a_via_stands_clear_of_its_own_pad_unless_asked_to_sit_in_it():
    """An SMD pad's own centre passes every rule, so without this the search
    recommended a via in the pad nearly every time - which needs plugging to
    stop solder wicking, and is not a tap reached by a tail."""
    u = footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("GND", "SIG"))
    g = _geom(fps=[u])
    gnd = next(p for p in u.pads if p.net == "GND")
    beside = queries.via_judge(g, gnd.box.center, "GND", 0.6, 0.3, 0.2, F, source=gnd.outlines)
    spot, tally, _ = queries.free_spot(gnd.box.center, beside, radius=3.0, step=0.1)
    from placemat.geometry import circle_polygon, polys_overlap
    ring = circle_polygon(spot.at, 0.3)
    assert not any(polys_overlap(ring, o) for o in gnd.outlines)
    assert tally["pad"] >= 1
    inside = queries.via_judge(g, gnd.box.center, "GND", 0.6, 0.3, 0.2, F)
    assert queries.free_spot(gnd.box.center, inside, radius=3.0, step=0.1)[0].distance == 0.0
