"""A written board's airwires join each net's islands as a spanning tree of their shortest links, the same whatever
order the islands and their points come in (kicad/airwires.py)."""
import random

from placemat.kicad.airwires import island_edges


def test_a_nets_islands_are_joined_by_their_shortest_links():
    islands = {"N": [[(0, 0), (1, 0)], [(5, 0), (9, 9)], [(5, 3)]]}
    assert island_edges(islands) == [("N", (5, 0), (5, 3)), ("N", (1, 0), (5, 0))]       # each link's ends in order


def test_an_island_alone_or_a_net_of_one_island_has_no_airwire():
    assert island_edges({"A": [[(0, 0), (1, 1)]], "B": []}) == []


def test_the_airwires_are_the_same_whatever_order_the_islands_and_points_come_in():
    rnd = random.Random(3)
    islands = {n: [[(rnd.randint(0, 20) / 2, rnd.randint(0, 20) / 2) for _ in range(4)] for _ in range(5)] for n in "ABC"}
    want = island_edges(islands)
    for _ in range(20):
        shuffled = {}
        for n in rnd.sample(sorted(islands), 3):
            groups = [rnd.sample(g, len(g)) for g in islands[n]]
            rnd.shuffle(groups)
            shuffled[n] = groups
        assert island_edges(shuffled) == want


def test_links_of_equal_length_are_taken_by_their_points():
    # (0, 0) is 1 from both (1, 0) and (0, 1): the link to the lower point stands, whichever island is given first
    a, b, c = [(0, 0)], [(1, 0)], [(0, 1)]
    assert island_edges({"N": [a, b, c]}) == island_edges({"N": [c, b, a]})
    assert island_edges({"N": [a, c]}) == [("N", (0, 0), (0, 1))]
