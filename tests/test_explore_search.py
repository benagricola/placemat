"""Scoring a variant and searching seeds in parallel under a deadline."""
import time

from placemat.explore import Explore, explore, score
from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


def _make():
    fps = [footprint("U1", 10, 10, w=8, h=4, inst="mcu", nets=("A", "B")),
           footprint("R1", 60, 60, w=2, h=1, inst="r1", nets=("A", "X")),
           footprint("R2", 60, 62, w=2, h=1, inst="r2", nets=("B", "Y")),
           footprint("R3", 60, 64, w=2, h=1, inst="r3", nets=("A", "B")),
           footprint("C1", 60, 66, w=2, h=1, inst="c1", nets=("B", "A"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=1.0)
    b.place(Part("mcu"), at=Location(20, 20))
    for k in ("r1", "r2", "r3", "c1"):
        b.place(Part(k))
    return b


FOCUS = frozenset({"r1", "r2", "r3", "c1"})


def test_the_score_orders_placed_findings_worst_cell_then_wire():
    b = _make()
    plan = b.resolve()
    s = score(b, plan)
    assert s[0] == -5 and s[1] == 0
    assert s[2] == int(plan.rudy.worst / 0.05 + 1e-9) and s[3] > 0
    assert score(b, plan, step=0)[2] == 0                 # left out
    assert b.settings.explore_congestion_step == 0.05     # the default, from the settings


def test_the_same_seeds_give_the_same_best_whatever_the_jobs():
    one = explore(_make, FOCUS, seconds=60, jobs=1, seeds=range(0, 12))
    two = explore(_make, FOCUS, seconds=60, jobs=2, seeds=range(0, 12))
    assert one.best_seed == two.best_seed and one.best == two.best
    assert one.tried == two.tried == 12


def test_seed_zero_is_always_tried_and_the_best_is_no_worse():
    r = explore(_make, FOCUS, seconds=60, jobs=2, seeds=range(3, 9))
    assert r.baseline == score(_make(), _make().resolve())
    assert r.best <= r.baseline and 0 in [s for s, _ in r.results]


def test_the_deadline_is_kept():
    t0 = time.time()
    r = explore(_make, FOCUS, seconds=2, jobs=2)
    assert time.time() - t0 < 2 + 10          # the deadline, plus a variant in flight and process start
    assert r.tried >= 2
