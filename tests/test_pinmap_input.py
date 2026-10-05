"""What the pin map study reads: the studied parts and their nets from the pads alone (a routed net keeps its airwire),
a net followed through a series part, each net's crossing class, and the other airwires."""

from placemat.board_geometry import NetClass
from placemat.pinmap_input import build, net_kind, outward, placed_from_geometry
from placemat.ratsnest import board_nets
from tests.fixtures import board_geometry, footprint, track
from tests.pinmap_boards import input_of, pad, point_pad, quad, quad_footprint, reversed_four, two_pad


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


def _eight(**kw):
    """U1 with two pins on each side (E 1-2, S 3-4, W 5-6, N 7-8), each net running to a test point far off."""
    nets = {s: ["%s%d" % (s, i) for i in (1, 2)] for s in "ESWN"}
    pads, u1 = quad("U1", 20, 20, nets, {"Pm.PinPool": "1-8"}, **kw)
    for i, net in enumerate(n for s in "ESWN" for n in nets[s]):
        pads += point_pad("TP%d" % i, net, 40 + i, 40)
    return pads, {"U1": u1}


def _normals(**kw):
    inp, problems = input_of(*_eight(**kw))
    assert problems == []
    return inp.part("U1"), {p.number: (p.nx, p.ny) for p in inp.part("U1").pins}


def test_the_pins_of_a_part_face_the_side_they_stand_on():
    _, got = _normals()
    assert got == {"1": (1, 0), "2": (1, 0), "3": (0, 1), "4": (0, 1), "5": (-1, 0), "6": (-1, 0), "7": (0, -1), "8": (0, -1)}


def test_a_part_turned_a_quarter_has_its_pins_facing_in_board_axes():
    part, got = _normals(rotation=90.0)
    assert part.rotation == 90.0
    assert got == {"1": (0, -1), "2": (0, -1), "3": (1, 0), "4": (1, 0), "5": (0, 1), "6": (0, 1), "7": (-1, 0), "8": (-1, 0)}


def test_a_part_on_the_back_has_its_pins_facing_in_board_axes():
    part, got = _normals(face="back")
    assert part.face == "back"
    assert got == {"1": (-1, 0), "2": (-1, 0), "3": (0, 1), "4": (0, 1), "5": (1, 0), "6": (1, 0), "7": (0, -1), "8": (0, -1)}


def test_a_net_with_several_pads_on_one_part_carries_the_pairs_of_them_that_touch():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"})
    pads += [pad("T1", 1, "A", 20, 9.5), pad("T1", 2, "A", 20.5, 9.5), pad("T2", 1, "A", 30, 9.5)] + point_pad("TP", "B", 25, 10)
    inp, _ = input_of(pads, {"U1": u1})
    a = next(n for n in inp.nets if n.net == "A")
    anchors = [(f.ref, f.number) for f in a.fixed]
    assert anchors == [("T1", "1"), ("T1", "2"), ("T2", "1")]
    assert a.joined == ((0, 1),)


def test_pair_plane_and_impedance_kinds_come_through_build():
    pads, u1 = quad("U1", 10, 10, {"E": ["P", "N", "Z", "Q"]}, {"Pm.PinPool": "1-4"})
    for i, net in enumerate(["P", "N", "Z", "Q"]):
        pads += point_pad("TP%d" % i, net, 20, 8.5 + i)
    pads += point_pad("J1", "GND", 30, 30) + point_pad("J2", "GND", 32, 30)
    classes = {"Z": NetClass("SE50", 0.1, 0.1, 0.4, 0.2, tuning_profile="SE50")}
    inp, _ = input_of(pads, {"U1": u1}, quiet={"GND"}, partners={"P": "N", "N": "P"}, netclasses=classes)
    assert {n.net: n.kind for n in inp.nets} == {"P": "pair", "N": "pair", "Z": "impedance", "Q": "plain"}
    assert [(w.net, w.kind) for w in inp.background] == [("GND", "plane")]


def test_only_a_part_whose_reference_prefix_is_listed_with_nets_on_both_pads_is_followed():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "C"]}, {"Pm.PinPool": "1-3"})
    pads += two_pad("R1", "A", "A_FAR", 15, 9) + point_pad("J1", "A_FAR", 30, 9)
    pads += two_pad("J2", "B", "B_FAR", 15, 10) + point_pad("J3", "B_FAR", 30, 10)         # a two-pin connector
    pads += [pad("FB1", 1, "C", 15, 11), pad("FB1", 2, "", 16, 11)] + point_pad("J4", "C", 30, 11)
    inp, _ = input_of(pads, {"U1": u1})
    got = {n.net: (n.via, n.far) for n in inp.nets}
    assert got == {"A": ("R1", "A_FAR"), "B": ("", ""), "C": ("", "")}
    inp, _ = input_of(pads, {"U1": u1}, prefixes=("J",))
    assert {n.net: n.via for n in inp.nets} == {"A": "", "B": "J2", "C": ""}


def test_a_far_net_two_studied_pins_reach_is_counted_once():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"})
    pads += two_pad("R1", "A", "F", 15, 9.5) + two_pad("R2", "B", "F", 15, 10.5)
    pads += point_pad("J1", "F", 30, 9.5) + point_pad("J2", "F", 30, 10.5)
    inp, _ = input_of(pads, {"U1": u1})
    a, b = (next(n for n in inp.nets if n.net == x) for x in ("A", "B"))
    assert (a.via, a.far, b.via, b.far) == ("R1", "F", "", "")
    assert [(f.ref, f.number) for f in a.fixed] == [("J1", "1"), ("J2", "1"), ("R2", "2")]
    assert [(f.ref, f.number) for f in b.fixed] == [("R2", "1")]
    anchors = [(f.ref, f.number) for n in inp.nets for f in n.fixed]
    assert len(anchors) == len(set(anchors))
