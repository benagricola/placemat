"""What the pin map study reads: the studied parts and their nets from the pads alone (a routed net keeps its airwire),
a net followed through a series part, each net's crossing class, and the other airwires."""

from placemat.board_geometry import NetClass
from placemat.pinmap_input import build, net_kind, outward, placed_from_geometry
from placemat.ratsnest import board_nets
from tests.fixtures import board_geometry, footprint, track
from tests.pinmap_boards import input_of, point_pad, quad, quad_footprint, reversed_four, two_pad


def test_the_studied_nets_carry_their_ends_and_anchors_and_the_rest_are_the_background():
    pads, parts = reversed_four()
    pads += two_pad("R9", "X", "Y", 30, 30) + point_pad("TP9", "X", 35, 30)
    inp, problems = input_of(pads, parts)
    assert problems == [] and [p.ref for p in inp.parts] == ["U1"]
    a = next(n for n in inp.nets if n.net == "A")
    assert a.ends == (("U1", "1"),) and [(f.ref, f.number) for f in a.fixed] == [("TP4", "1")]
    assert {w.net for w in inp.background} == {"X"}
    assert inp.parts[0].slots.movable == ("A", "B", "C", "D")


def test_a_board_without_a_pool_has_nothing_to_study():
    pads, parts = reversed_four(fields={})
    assert input_of(pads, parts) == (None, [])


def test_a_routed_net_keeps_its_airwire_for_the_study_is_scored_from_the_pads_alone():
    fps = [quad_footprint("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"}),
           footprint("R1", 20, 9.5, w=2, h=1, inst="r1", nets=("A", "N1")),
           footprint("R2", 20, 10.5, w=2, h=1, inst="r2", nets=("B", "N2"))]
    a1 = fps[0].pads[0].airwire_end
    r1 = fps[1].pads[0].airwire_end
    routed = board_geometry(fps, copper=[track("A", a1.x, a1.y, r1.x, r1.y)], width=40, height=40)
    bare = board_geometry(fps, width=40, height=40)
    joined = board_nets([(c.owner, "", c.net, c.layers, c.outlines, c.box, c.box.center) for c in routed.copper
                         if c.kind == "pad"], [(c.kind, c.net, c.layers, c.outlines, c.box, c.anchors)
                                               for c in routed.copper if c.kind == "track"])
    assert joined["A"][1]                                      # with its copper, KiCad's ratsnest has no airwire for A
    got = [build(*placed_from_geometry(g)[:2], {}, frozenset(), {}, g.netclasses)[0] for g in (routed, bare)]
    assert got[0] == got[1]
    a = next(n for n in got[0].nets if n.net == "A")
    assert a.ends == (("U1", "1"),) and [(f.ref, f.number) for f in a.fixed] == [("R1", "1")]


def test_a_net_through_a_series_part_is_followed_to_the_far_net():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"})
    parts = {"U1": u1}
    pads += two_pad("R1", "A", "A_FAR", 15, 9.5) + point_pad("J1", "A_FAR", 30, 9.5)
    pads += two_pad("R2", "B", "B_OPEN", 15, 10.5)                 # its far net goes nowhere else: not followed
    inp, _ = input_of(pads, parts)
    a, b = (next(n for n in inp.nets if n.net == x) for x in ("A", "B"))
    assert (a.via, a.far, [(f.ref, f.number) for f in a.fixed]) == ("R1", "A_FAR", [("J1", "1")])
    assert (b.via, b.far, [(f.ref, f.number) for f in b.fixed]) == ("", "", [("R2", "1")])
    assert "A_FAR" not in {w.net for w in inp.background}
    inp, _ = input_of(pads, parts, follow=False)
    assert next(n for n in inp.nets if n.net == "A").via == ""


def test_a_nets_crossing_class_is_plane_pair_impedance_or_plain():
    classes = {"Z": NetClass("SE50", 0.1, 0.1, 0.4, 0.2, tuning_profile="SE50"), "P": NetClass("Default", 0.1, 0.1, 0.4, 0.2)}
    assert net_kind("GND", {"GND"}, {}, classes) == "plane"
    assert net_kind("P", set(), {"P": "N"}, classes) == "pair"
    assert net_kind("Z", set(), {}, classes) == "impedance"
    assert net_kind("P", set(), {}, classes) == "plain"


def test_a_pin_faces_the_side_of_the_box_it_is_nearest_ties_going_east_south_west_north():
    assert outward(1.7, 0.2, 2.0, 2.0) == (1.0, 0.0)
    assert outward(0.2, 1.7, 2.0, 2.0) == (0.0, 1.0)
    assert outward(-1.7, 0.0, 2.0, 2.0) == (-1.0, 0.0)
    assert outward(0.0, -1.7, 2.0, 2.0) == (0.0, -1.0)
    assert outward(1.7, 1.7, 2.0, 2.0) == (1.0, 0.0)                  # a corner pin: east before south
