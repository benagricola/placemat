"""Scoring a variant and searching seeds in parallel under a deadline."""
import time

from placemat.explore import explore, score
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


def test_a_variant_is_scored_by_the_run_score_with_the_worst_cell_in_it():
    from placemat import score as run_score
    from placemat.explore import measure
    b = _make()
    plan = b.resolve()
    m = measure(b, plan)
    assert m["unplaced"] == {} and m["rudy_steps"] == int(plan.rudy.worst / 0.05 + 1e-9)
    assert score(b, plan) == run_score.total(m, b.settings)
    assert "rudy_steps" not in measure(b, plan, step=0)          # left out
    assert b.settings.explore_congestion_step == 0.05             # the default, from the settings


def test_the_same_seeds_give_the_same_best_whatever_the_jobs():
    one = explore(_make, FOCUS, seconds=60, jobs=1, seeds=range(0, 12))
    two = explore(_make, FOCUS, seconds=60, jobs=2, seeds=range(0, 12))
    assert one.best_seed == two.best_seed and one.best == two.best and one.best_measures == two.best_measures
    assert one.tried == two.tried == 12


def test_seed_zero_is_always_tried_and_the_best_is_no_worse():
    r = explore(_make, FOCUS, seconds=60, jobs=2, seeds=range(3, 9))
    assert r.baseline == score(_make(), _make().resolve())
    assert r.best <= r.baseline and 0 in [s for s, _, _ in r.results]


def test_the_deadline_is_kept():
    t0 = time.time()
    r = explore(_make, FOCUS, seconds=2, jobs=2)
    assert time.time() - t0 < 2 + 10          # the deadline, plus a variant in flight and process start
    assert r.tried >= 2


def test_when_the_time_passes_with_variants_in_flight_they_finish_and_the_explore_says_which(tmp_path, monkeypatch, capsys):
    from placemat import channel, explore as ex
    from tests import explore_boards as eb
    sent = []

    class Rep:
        def send(self, ev):
            sent.append(ev)
    monkeypatch.setattr(channel, "current", lambda: Rep())
    r = explore(eb.Recording(tmp_path / "pids", delay=8.0), eb.FOCUS, seconds=6, jobs=2)
    (passed,) = [e for e in sent if e["ev"] == "explore_budget_passed"]
    assert passed["budget"] == 6 and passed["t"] >= 6
    seeds = [f["seed"] for f in passed["finishing"]]
    assert seeds and all(0 <= f["started"] < 6 for f in passed["finishing"])
    landed = [e["seed"] for e in sent if e["ev"] == "variant"]
    assert set(seeds) <= set(landed) and r.tried == 1 + len(landed)                # kept: they ran to the end and count
    names = [e["ev"] for e in sent]
    assert all(names.index("explore_budget_passed") < i for i, e in enumerate(sent) if e["ev"] == "variant" and e["seed"] in seeds)
    line = ex.budget_passed_line(passed)
    assert line in capsys.readouterr().out and line.startswith("  the explore's time, 6 s, has passed; ")


def test_the_budget_line_names_each_variant_still_finishing_and_when_it_began():
    from placemat.explore import budget_passed_line
    line = budget_passed_line({"t": 900.2, "budget": 900, "finishing": [{"seed": 41, "started": 782.0}, {"seed": 42, "started": 840.0}]})
    assert line == "  the explore's time, 15 min, has passed; 2 variants started before it are finishing: seed 41 from 13 min 2 s in, seed 42 from 14 min in"


def test_an_explore_of_fixed_seeds_has_no_time_to_pass(monkeypatch):
    from placemat import channel
    sent = []
    monkeypatch.setattr(channel, "current", lambda: type("R", (), {"send": lambda self, ev: sent.append(ev)})())
    explore(_make, FOCUS, seconds=0.001, jobs=2, seeds=range(0, 4))
    assert not [e for e in sent if e["ev"] == "explore_budget_passed"]
