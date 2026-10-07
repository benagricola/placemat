"""The ratsnest's crossing price by net kind: the dearer kind prices a crossing, a quiet net first, a pair's own
crossing at its own price; Python and native agree."""
import random

import pytest

from placemat.ratsnest import (KIND_IMPEDANCE, KIND_PAIR, KIND_PLAIN, KIND_PLANE, Anchor, Edge, Ratsnest,
                               crossing_price, crossings)

PRICES = (1.0, 3.0, 5.0, 0.0, 25.0)        # plain, impedance, pair net, plane, a pair with itself


def _x(net_a, net_b):
    a = Edge(net_a, Anchor("A", "1", 0.0, 0.0), Anchor("B", "1", 2.0, 2.0))
    b = Edge(net_b, Anchor("C", "1", 0.0, 2.0), Anchor("D", "1", 2.0, 0.0))
    return [a, b]


def test_the_dearer_kind_prices_a_crossing():
    kinds = {"P": KIND_PAIR, "S": KIND_PLAIN, "Z": KIND_IMPEDANCE, "G": KIND_PLANE, "N": KIND_PAIR}
    partners = {"P": "N", "N": "P"}
    assert crossing_price(kinds, partners, PRICES, "P", "S") == 5.0
    assert crossing_price(kinds, partners, PRICES, "Z", "S") == 3.0
    assert crossing_price(kinds, partners, PRICES, "S", "S2") == 1.0
    assert crossing_price(kinds, partners, PRICES, "P", "G") == 0.0       # a quiet net first: R1
    assert crossing_price(kinds, partners, PRICES, "P", "N") == 25.0      # a pair crossing itself
    assert crossing_price(kinds, partners, PRICES, "P", "Z") == 5.0       # the dearer of pair and impedance


def test_crossings_sums_the_prices():
    kinds = {"P": KIND_PAIR, "S": KIND_PLAIN}
    assert crossings(_x("P", "S"), kinds=kinds, prices=PRICES)[0] == 5.0


def test_crossings_default_prices_count_one_each():
    assert crossings(_x("P", "S"))[0] == 1.0


def _rn(mirror=None):
    kinds = {"P": KIND_PAIR, "N": KIND_PAIR, "Z": KIND_IMPEDANCE, "G": KIND_PLANE}
    return Ratsnest(kinds, mirror=mirror, partners={"P": "N", "N": "P"}, prices=PRICES)


def test_a_candidate_leaf_is_priced_by_the_dearer_kind():
    rn = _rn()
    rn.set_net("S", [Anchor("U1", "1", 0, 0), Anchor("R1", "1", 10, 10)])
    rn.set_net("G", [Anchor("U1", "2", 0, 10)])
    # a leaf of P from (10, 0) to U1's pad (0, 10) crosses S's airwire (5), and G's leaf is a plane's (0, kept out)
    rn.set_net("P", [Anchor("U1", "3", 0, 10)])
    assert rn.leaf_costs([("P", 10.0, 0.0)])[0] == 5.0
    rn.set_net("Z", [Anchor("U1", "4", 0, 10)])
    assert rn.leaf_costs([("Z", 10.0, 0.0)])[0] == 3.0
    assert rn.leaf_costs([("G", 10.0, 0.0)])[0] == 0.0


native = pytest.importorskip("placemat_native")


@pytest.mark.parametrize("seed", range(6))
def test_native_prices_by_kind_as_python_does(seed):
    rng = random.Random(500 + seed)
    kinds = {"N%d" % n: rng.choice((KIND_PLAIN, KIND_IMPEDANCE, KIND_PAIR, KIND_PLANE)) for n in range(12)}
    partners = {}
    for a, b in (("N2", "N3"), ("N4", "N5")):
        kinds[a] = kinds[b] = KIND_PAIR
        partners[a], partners[b] = b, a
    py = Ratsnest(kinds, partners=partners, prices=PRICES)
    nat = Ratsnest(kinds, mirror=native.NativeRatsnest(), partners=partners, prices=PRICES)
    for n in range(12):
        pts = [Anchor(rng.choice(["P%d" % i for i in range(8)] + [""]), str(i),
                      round(rng.uniform(0, 20) / 0.5) * 0.5, round(rng.uniform(0, 20) / 0.5) * 0.5)
               for i in range(rng.randint(1, 5))]
        py.set_net("N%d" % n, pts)
        nat.set_net("N%d" % n, pts)
    names = sorted(kinds)
    for _ in range(300):
        pads = [(rng.choice(names), round(rng.uniform(0, 20) / 0.25) * 0.25, round(rng.uniform(0, 20) / 0.25) * 0.25)
                for _ in range(rng.randint(1, 5))]
        own = frozenset(rng.sample(["P%d" % i for i in range(8)], rng.randint(0, 2)))
        assert nat.leaf_costs(pads, own, 1.0) == Ratsnest.leaf_costs(py, pads, own, 1.0)
