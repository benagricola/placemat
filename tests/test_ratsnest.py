"""placemat's ratsnest: KiCad's per-net minimum spanning tree over the pad
anchors, pads already joined by copper counted as one, and the crossings
between the edges of different nets."""
import random

import pytest

from placemat.ratsnest import Anchor, Ratsnest, crossings, mst, segments_cross


def A(ref, x, y, number="1"):
    return Anchor(ref, number, x, y)


def pairs(edges):
    return sorted(tuple(sorted((e.a.ref, e.b.ref))) for e in edges)


def test_a_net_of_two_pads_is_one_edge_and_of_one_pad_none():
    assert pairs(mst("N", [A("a", 0, 0), A("b", 3, 4)])) == [("a", "b")]
    assert mst("N", [A("a", 0, 0)]) == []


def test_the_tree_is_the_shortest_that_joins_every_pad():
    pts = [A("a", 0, 0), A("b", 1, 0), A("c", 5, 0), A("d", 5, 1), A("e", 2, 3)]
    got = pairs(mst("N", pts))
    assert got == [("a", "b"), ("b", "e"), ("c", "d"), ("d", "e")]     # d-e (3.61) beats b-c (4.00)


def test_it_is_the_minimum_spanning_tree_on_random_nets():
    """Checked against Prim's algorithm over every pair: the total length of
    the tree is the minimum (the edge set may differ only where lengths tie)."""
    import math
    rng = random.Random(7)
    for _ in range(50):
        pts = [A("p%d" % i, round(rng.uniform(0, 20), 3), round(rng.uniform(0, 20), 3)) for i in range(rng.randint(2, 25))]
        tree = mst("N", pts)
        assert len(tree) == len(pts) - 1
        best = {0}
        total = 0.0
        while len(best) < len(pts):
            d, j = min((math.hypot(pts[i].x - pts[k].x, pts[i].y - pts[k].y), k)
                       for i in best for k in range(len(pts)) if k not in best)
            best.add(j)
            total += d
        assert sum(math.hypot(e.a.x - e.b.x, e.a.y - e.b.y) for e in tree) == pytest.approx(total, abs=1e-5)


def test_pads_joined_by_copper_get_no_edge_between_them():
    pts = [A("a", 0, 0), A("b", 1, 0), A("c", 10, 0)]
    got = mst("N", pts, joined=[(0, 1)])
    assert pairs(got) == [("b", "c")]                  # a and b are one cluster; its nearest member reaches c


def test_equal_lengths_are_broken_by_kicads_order_the_lower_position_first():
    # b and c are both 1 mm from a: KiCad sorts equal weights by the lower end's position, x then y
    pts = [A("a", 0, 0), A("b", 0, 1), A("c", 1, 0), A("d", 1, 1)]
    assert pairs(mst("N", pts)) == [("a", "b"), ("a", "c"), ("b", "d")]


def test_collinear_pads_are_joined_in_a_chain():
    pts = [A("a", 0, 0), A("c", 2, 0), A("b", 1, 0), A("d", 3, 0)]
    assert pairs(mst("N", pts)) == [("a", "b"), ("b", "c"), ("c", "d")]


def test_segments_cross_only_where_they_properly_intersect():
    assert segments_cross((0, 0), (2, 2), (0, 2), (2, 0))
    assert not segments_cross((0, 0), (1, 1), (2, 2), (3, 3))
    assert not segments_cross((0, 0), (2, 0), (0, 1), (2, 1))


def test_crossings_count_each_pair_of_different_nets_once_and_never_one_net_with_itself():
    edges = mst("A", [A("a1", 0, 0), A("a2", 2, 2)]) + mst("B", [A("b1", 0, 2), A("b2", 2, 0)]) \
        + mst("C", [A("c1", 1, -1), A("c2", 1, 3)])
    n, per_net = crossings(edges)
    assert n == 3 and per_net == {"A": 2, "B": 2, "C": 2}
    same = mst("A", [A("x", 0, 0), A("y", 2, 2), A("z", 0, 2), A("w", 2, 0)])
    assert crossings(same)[0] == 0


def test_a_crossing_is_weighted_by_the_lighter_of_its_two_nets():
    edges = mst("SIG", [A("a", 0, 0), A("b", 2, 2)]) + mst("GND", [A("g1", 0, 2), A("g2", 2, 0)])
    assert crossings(edges, weights={"GND": 0.0})[0] == 0.0
    assert crossings(edges, weights={"GND": 0.25})[0] == 0.25


def test_the_ratsnest_counts_what_a_candidate_would_add_as_a_leaf_join():
    r = Ratsnest()
    r.set_net("A", [A("a1", 0, 0), A("a2", 4, 0)])
    r.set_net("B", [A("b1", 2, -3)])
    # a candidate part with a B pad at (2, 3): its leaf edge to b1 crosses a1-a2
    assert r.added([("B", 2, 3)], own=set()) == 1
    # the same pad on the far side joins b1 without crossing anything
    assert r.added([("B", 2, -5)], own=set()) == 0
    # two pads of different nets of the one candidate crossing each other count too
    r2 = Ratsnest()
    r2.set_net("A", [A("a1", 0, 0)])
    r2.set_net("B", [A("b1", 0, 2)])
    assert r2.added([("A", 2, 2), ("B", 2, 0)], own=set()) == 1


def test_added_matches_a_full_recount_for_a_leaf_join_on_random_boards():
    rng = random.Random(3)
    for _ in range(40):
        nets = {n: [A("%s%d" % (n, i), rng.uniform(0, 20), rng.uniform(0, 20)) for i in range(rng.randint(1, 5))]
                for n in "ABCD"}
        r = Ratsnest()
        for n, pts in nets.items():
            r.set_net(n, pts)
        before = crossings(r.edges())[0]
        net = rng.choice("ABCD")
        x, y = rng.uniform(0, 20), rng.uniform(0, 20)
        near = min(nets[net], key=lambda p: (p.x - x) ** 2 + (p.y - y) ** 2)
        leaf = mst(net, [near, A("new", x, y)])
        after = crossings(r.edges() + leaf)[0]
        assert r.added([(net, x, y)], own=set()) == after - before


def test_a_candidates_own_part_is_not_joined_to_itself():
    r = Ratsnest()
    r.set_net("A", [A("u1", 0, 0), A("r1", 5, 0)])
    # a pad of r1 being re-placed: its nearest placed A pad must not be r1's own old one
    assert r.added([("A", 6, 0)], own={"r1"}) == 0
    r.set_net("B", [A("b1", 5.5, -1), A("b2", 5.5, 1)])
    assert r.added([("A", 6, 0)], own={"r1"}) == 1     # joins u1, across b1-b2


def test_an_airwire_ending_on_another_touches_it_and_does_not_cross_either_way_round():
    a, b = (147.24, 104.67), (148.2715, 103.11)          # ends on the vertical c-d
    c, d = (147.24, 105.32), (147.24, 104.02)
    for p, q in ((a, b), (b, a)):
        for r, s in ((c, d), (d, c)):
            assert not segments_cross(p, q, r, s)
            assert not segments_cross(r, s, p, q)
    assert not segments_cross((0, 0), (2, 0), (1, 0), (3, 0))      # collinear overlap is not a crossing either


def test_a_track_joins_the_pads_it_touches_and_its_ends_are_nodes():
    from placemat.ratsnest import board_nets
    from placemat.values import Box, CopperLayer, Location
    F = frozenset([CopperLayer.F])

    def pad(ref, x, y):
        box = Box(x - 0.5, y - 0.5, x + 0.5, y + 0.5)
        return (ref, "1", "N", F, (((box.left, box.top), (box.right, box.top), (box.right, box.bottom), (box.left, box.bottom)),),
                box, Location(x, y))
    track_box = Box(0.0, -0.1, 5.0, 0.1)
    track = ("track", "N", F, (((0.0, -0.1), (5.0, -0.1), (5.0, 0.1), (0.0, 0.1)),), track_box, ((0.0, 0.0), (5.0, 0.0)))
    nets = board_nets([pad("a", 0, 0), pad("b", 20, 0), pad("c", 5.3, 0)], [track])
    anchors, joined = nets["N"]
    tree = mst("N", anchors, joined)
    ends = sorted(tuple(sorted((e.a.ref, e.b.ref))) for e in tree)
    assert ends == [("b", "c")]                     # a, c and the track are one cluster; c is its node nearest b
    # on another layer the track joins nothing
    B = frozenset([CopperLayer.B])
    anchors, joined = board_nets([pad("a", 0, 0), pad("c", 5.3, 0)], [("track", "N", B) + track[3:]])["N"]
    assert len(mst("N", anchors, joined)) == 2      # a-track end, track end-c... or a-c: two airwires, nothing joined
