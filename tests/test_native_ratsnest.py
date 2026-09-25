"""The native ratsnest mirror answers `leaf_costs` as the Python Ratsnest
does, exactly: the weighted crossings a candidate's leaf airwires add and
the escapes they cross, with quiet nets weighted, own parts left out, and
nets replaced as parts move."""
import random

import pytest

native = pytest.importorskip("placemat_native")

from placemat.ratsnest import Anchor, Ratsnest, mst  # noqa: E402


def _random_board(rng, weights):
    py = Ratsnest(weights)
    nat = Ratsnest(weights, mirror=native.NativeRatsnest(weights))
    nets = {}
    parts = ["P%d" % i for i in range(30)] + [""]
    for n in range(rng.randint(5, 40)):
        net = "N%d" % n
        k = rng.randint(1, 8)
        grid = rng.choice((0.25, 0.5, 1.0))
        pts = [Anchor(rng.choice(parts), str(i), round(rng.uniform(0, 40) / grid) * grid,
                      round(rng.uniform(0, 40) / grid) * grid) for i in range(k)]
        nets[net] = pts
    for net, pts in nets.items():
        py.set_net(net, pts)
        nat.set_net(net, pts)
    return py, nat, nets


@pytest.mark.parametrize("seed", range(12))
def test_leaf_costs_are_the_pythons_exactly(seed):
    rng = random.Random(seed)
    weights = {"N0": 0.0, "N1": 0.25, "N2": 0.0}
    py, nat, nets = _random_board(rng, weights)
    names = sorted(nets)
    for trial in range(400):
        if trial % 50 == 49:                     # a part moves: its nets are worked out again
            net = rng.choice(names)
            pts = [Anchor(a.ref, a.number, round(rng.uniform(0, 40), 3), round(rng.uniform(0, 40), 3))
                   for a in nets[net]]
            nets[net] = pts
            py.set_net(net, pts)
            nat.set_net(net, pts)
        pads = [(rng.choice(names + ["NEW"]), round(rng.uniform(0, 40) / 0.25) * 0.25,
                 round(rng.uniform(0, 40) / 0.25) * 0.25) for _ in range(rng.randint(1, 6))]
        own = frozenset(rng.sample(["P%d" % i for i in range(30)], rng.randint(0, 3)))
        depth = rng.choice((0.5, 1.0, 3.0))
        want = Ratsnest.leaf_costs(py, pads, own, depth)
        got = nat.leaf_costs(pads, own, depth)
        assert got == want, (seed, trial, pads, own, depth)


@pytest.mark.parametrize("seed", range(6))
def test_leaf_costs_with_pairs_are_the_pythons_exactly(seed):
    """With pairs among the nets, a crossing between partners weighs the pair
    weight in the native mirror exactly as in Python."""
    rng = random.Random(100 + seed)
    weights = {"N1": 0.25}
    partners = {}
    for a, b in (("N2", "N3"), ("N4", "N5"), ("N6", "N7")):
        partners[a], partners[b] = b, a
    py = Ratsnest(weights, partners=partners, pair_weight=25.0)
    mirror = native.NativeRatsnest(weights)
    mirror.set_partners(sorted(partners.items()), 25.0)
    nat = Ratsnest(weights, mirror=mirror, partners=partners, pair_weight=25.0)
    nets = {}
    for n in range(12):
        pts = [Anchor(rng.choice(["P%d" % i for i in range(8)] + [""]), str(i),
                      round(rng.uniform(0, 20) / 0.5) * 0.5, round(rng.uniform(0, 20) / 0.5) * 0.5)
               for i in range(rng.randint(1, 5))]
        nets["N%d" % n] = pts
        py.set_net("N%d" % n, pts)
        nat.set_net("N%d" % n, pts)
    names = sorted(nets)
    for _ in range(300):
        pads = [(rng.choice(names), round(rng.uniform(0, 20) / 0.25) * 0.25, round(rng.uniform(0, 20) / 0.25) * 0.25)
                for _ in range(rng.randint(1, 5))]
        own = frozenset(rng.sample(["P%d" % i for i in range(8)], rng.randint(0, 2)))
        assert nat.leaf_costs(pads, own, 1.0) == Ratsnest.leaf_costs(py, pads, own, 1.0)
