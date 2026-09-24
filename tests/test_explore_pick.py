"""The draw a focused item makes among its scanned candidates: best first,
never beyond the slack, the best the likeliest."""
import random
from collections import Counter

from placemat.explore import draw
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.placer import scan
from placemat.values import Face, Location
from tests.fixtures import board_geometry, footprint


def _cands(scores):
    return [(s, 0.0, 0, "c%d" % k) for k, s in enumerate(scores)]


def test_a_draw_never_goes_beyond_the_slack():
    rng = random.Random(1)
    cands = _cands([10.0, 11.0, 12.4, 12.6, 30.0])
    for _ in range(2000):
        assert draw(cands, rng, 0.25)[0] <= 12.5


def test_with_a_best_of_nothing_the_slack_is_in_millimetres():
    rng = random.Random(1)
    cands = _cands([0.0, 0.2, 0.3])
    assert {draw(cands, rng, 0.25)[0] for _ in range(500)} == {0.0, 0.2}


def test_the_best_is_the_likeliest():
    rng = random.Random(2)
    cands = _cands([10.0, 10.5, 11.0, 11.5])
    n = Counter(draw(cands, rng, 0.25)[3] for _ in range(10000))
    assert n["c0"] > n["c1"] > n["c2"] > n["c3"] > 0


def test_a_scan_picks_as_told_and_by_default_takes_the_best():
    fps = [footprint("R1", 30, 30, w=2, h=1, inst="r1")]
    occ = Occupancy(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    item = fps[0]
    hint = Placement(Location(30, 30), 0, Face.FRONT)
    score = lambda p: abs(p.location.x - 30) + abs(p.location.y - 30)
    seen = []

    def last(cands):
        seen.append([c[:3] for c in cands])
        return cands[-1]
    plain = scan(occ, item, hint, 2.0, 0.5, (0,), score=score)
    picked = scan(occ, item, hint, 2.0, 0.5, (0,), score=score, pick=last)
    assert plain.chosen.location == Location(30, 30)
    assert seen and seen[0] == sorted(seen[0])                 # best first
    assert picked.chosen != plain.chosen
