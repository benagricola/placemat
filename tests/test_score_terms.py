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


# ------------------------------------------------------------ the keep rule and net kinds
def test_a_zero_priced_impedance_net_still_crosses_a_pair_net_at_the_pair_price():
    prices = (1.0, 0.0, 5.0, 0.0, 25.0)
    kinds = {"Z": KIND_IMPEDANCE, "P": KIND_PAIR, "N": KIND_PAIR}
    partners = {"P": "N", "N": "P"}
    edges = _x("Z", "P")
    assert crossings(edges, kinds=kinds, partners=partners, prices=prices)[0] == 5.0
    rn = Ratsnest(kinds, partners=partners, prices=prices)
    rn.set_net("Z", [Anchor("U1", "1", 0, 0), Anchor("R1", "1", 10, 10)])
    rn.set_net("P", [Anchor("U1", "2", 0, 10)])
    assert rn.edges()                                   # the impedance net is kept
    assert rn.leaf_costs([("P", 10.0, 0.0)])[0] == 5.0
    # a quiet net at price 0 is not kept, unless it is a pair's half
    rq = Ratsnest({"G": KIND_PLANE}, prices=prices)
    rq.set_net("G", [Anchor("U1", "1", 0, 0), Anchor("R1", "1", 10, 10)])
    assert rq.edges() == []


@pytest.mark.parametrize("seed", range(4))
def test_native_keeps_a_zero_priced_kind_as_python_does(seed):
    rng = random.Random(900 + seed)
    prices = (1.0, 0.0, 5.0, 0.0, 25.0)
    kinds = {"N%d" % n: rng.choice((KIND_PLAIN, KIND_IMPEDANCE, KIND_PAIR, KIND_PLANE)) for n in range(10)}
    py = Ratsnest(kinds, prices=prices)
    nat = Ratsnest(kinds, mirror=native.NativeRatsnest(), prices=prices)
    for n in range(10):
        pts = [Anchor("P%d" % rng.randint(0, 6), str(i), round(rng.uniform(0, 20) / 0.5) * 0.5,
                      round(rng.uniform(0, 20) / 0.5) * 0.5) for i in range(rng.randint(1, 5))]
        py.set_net("N%d" % n, pts)
        nat.set_net("N%d" % n, pts)
    names = sorted(kinds)
    for _ in range(200):
        pads = [(rng.choice(names), round(rng.uniform(0, 20) / 0.25) * 0.25, round(rng.uniform(0, 20) / 0.25) * 0.25)
                for _ in range(rng.randint(1, 5))]
        assert nat.leaf_costs(pads, frozenset(), 1.0) == Ratsnest.leaf_costs(py, pads, frozenset(), 1.0)


def test_net_kinds_and_the_ratsnest_prices_of_a_board():
    import dataclasses
    from placemat.board_geometry import NetClass
    from placemat.occupancy import Occupancy, net_kinds
    from placemat.settings import Settings
    from tests.fixtures import board_geometry, footprint
    fps = [footprint("U1", 10, 10, inst="u1", nets=("DP", "DN")),
           footprint("U2", 30, 10, inst="u2", nets=("Z", "GND")),
           footprint("R1", 30, 30, inst="r1", nets=("S", "DP"))]
    g = board_geometry(fps)
    classes = dict(g.netclasses)
    classes["DP"] = NetClass("USB", 0.2, 0.2, 0.6, 0.3, diff_pair_width=0.15, diff_pair_gap=0.15)
    classes["DN"] = NetClass("USB", 0.2, 0.2, 0.6, 0.3, diff_pair_width=0.15, diff_pair_gap=0.15)
    classes["Z"] = NetClass("SE50", 0.1, 0.2, 0.6, 0.3, tuning_profile="SE50")
    g = dataclasses.replace(g, netclasses=classes)
    assert net_kinds(g, frozenset({"GND"})) == {"DP": KIND_PAIR, "DN": KIND_PAIR, "Z": KIND_IMPEDANCE, "GND": KIND_PLANE}
    s = Settings()
    occ = Occupancy(g, 0.5, settings=s)
    occ.quiet_nets = frozenset({"GND"})
    assert occ.ratsnest().prices == (1.0, s.score_impedance, s.score_crossing_pair_net, s.score_crossing_plane,
                                     s.score_pair_crossing / s.score_crossing)


# ------------------------------------------------------------ the new terms
from placemat import score  # noqa: E402
from placemat.settings import Settings  # noqa: E402


def test_link_and_area_are_priced():
    m = {"v": 2, "link_mm": 12.5, "area_mm2": 100.0, "airwire_mm": 10.0, "airwire_impedance_mm": 4.0, "crossings": {},
         "rudy_steps": 2}
    s = Settings()
    t = score.terms(m, s)
    assert t["airwire"] == 10.0 + (s.score_impedance - 1.0) * 4.0
    assert t["link"] == s.score_link * 12.5
    assert t["area"] == s.score_area * 100.0
    assert t["congestion"] == s.score_congestion * 2


def test_crossings_by_kind():
    s = Settings()
    m = {"v": 2, "crossings": {"plain+plain": 2, "impedance+plain": 1, "pair_net+plain": 1, "impedance+pair_net": 1,
                               "plane": 3, "pair": 1}}
    want = s.score_crossing * (2 + s.score_impedance + 2 * s.score_crossing_pair_net
                               + s.score_crossing_plane * 3) + s.score_pair_crossing
    assert abs(score.terms(m, s)["crossings"] - want) < 1e-9


def test_old_measures_are_not_comparable():
    from placemat.report import RunRecord, comparable
    old = RunRecord.of({"run_id": "x", "board": "b", "status": "ok",
                       "metrics": {"drc_real": 0, "airwire_mm": 1.0, "measures": {"airwire_mm": 1.0}}})
    assert not comparable(old)
    new = RunRecord.of({"run_id": "y", "board": "b", "status": "ok",
                       "metrics": {"drc_real": 0, "airwire_mm": 1.0,
                                    "measures": {"airwire_mm": 1.0, "v": score.MEASURES_VERSION}}})
    assert comparable(new)


def test_the_moved_congestion_step_is_refused_naming_its_new_key(tmp_path):
    from placemat.settings import SettingsError, load
    (tmp_path / "placemat.toml").write_text("[explore]\ncongestion_step = 0.1\n")
    with pytest.raises(SettingsError, match=r"explore\.congestion_step is now score\.congestion_step"):
        load(tmp_path)


def test_crossings_are_tallied_in_the_class_that_priced_them():
    kinds = {"P": KIND_PAIR, "N": KIND_PAIR, "Z": KIND_IMPEDANCE, "G": KIND_PLANE}
    partners = {"P": "N", "N": "P"}
    prices = (1.0, 3.0, 5.0, 0.0, 25.0)
    for a, b, want in (("P", "S", "plain+pair_net"), ("Z", "S", "plain+impedance"), ("S", "T", "plain+plain"),
                       ("P", "G", "plane"), ("P", "N", "pair"), ("P", "Z", "impedance+pair_net")):
        total, _, tally = crossings(_x(a, b), kinds=kinds, partners=partners, prices=prices)
        assert tally == {want: 1}, (a, b)
    # the key does not move with the prices
    assert crossings(_x("P", "Z"), kinds=kinds, partners=partners, prices=(1, 9, 0, 0, 1))[2] == {"impedance+pair_net": 1}


def test_the_prices_of_settings_are_in_class_order():
    from placemat.ratsnest import prices_of
    s = Settings()
    assert prices_of(s) == (1.0, s.score_impedance, s.score_crossing_pair_net, s.score_crossing_plane,
                            s.score_pair_crossing / s.score_crossing)
