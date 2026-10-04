"""A step's search budget (`place.step_budget`, `place(budget=)`): the candidates a step may judge, over all its passes and
the carried vias' giving way. A step that spends it takes the best spot found so far or is left unplaced, with a finding
that carries the measurement."""
import dataclasses

import pytest

from placemat import placer
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Face, Location
from tests.fixtures import board_geometry, footprint
from tests.suggest_support import apply_and_resolve, resolve, suggestions_of

SEARCH = '''board.place(Part("u1"), at=Location(30, 30))
board.place(Part("j1"), at=Near(Location(30, 30), radius=30, step=0.5), %s)
board.place(Part("c1"), at=Location(50, 50))
board.place(Part("r1"), at=Location(50, 20))
'''
TURNS = (0.0, 90.0)


def _board(item_w=6.0):
    fps = [footprint("U%d" % k, 6 + 8 * (k % 6), 6 + 8 * (k // 6), w=4.0, h=3.0, nets=("N%d" % k, "M%d" % k)) for k in range(30)]
    fps.append(footprint("X1", 25, 25, w=item_w, h=3.0, nets=("A", "B")))
    occ = Occupancy(board_geometry(fps, width=50.0, height=50.0), edge_margin=0.5)
    for fp in fps[:-1]:
        occ.commit(fp, Placement(fp.location, fp.rotation, fp.face))
    item = fps[-1]
    occ.pending |= occ._geometry(item).owners
    return occ, item, Placement(Location(25, 25), 0.0, Face.FRONT)


@pytest.fixture(params=[True, False], ids=["native", "python"])
def sweep(request, monkeypatch):
    monkeypatch.setattr(placer, "NATIVE_SWEEP", request.param)
    return request.param


def _scan(occ, item, hint, budget, radius=12.0, **kw):
    occ.step_budget = None if budget is None else placer.SearchBudget(budget)
    return placer.scan(occ, item, hint, radius, 0.2, TURNS, None, **kw)


def test_a_budget_that_is_not_spent_changes_nothing(sweep):
    occ, item, hint = _board(item_w=70.0)           # wider than the board: no legal spot, every candidate judged
    free = _scan(occ, item, hint, None)
    roomy = _scan(occ, item, hint, 10 ** 9)
    assert (roomy.chosen, roomy.tried, roomy.rejected, roomy.reasons, roomy.blockers) == \
        (free.chosen, free.tried, free.rejected, free.reasons, free.blockers)
    assert roomy.cut is None and free.cut is None
    assert occ.step_budget.judged == free.tried and occ.step_budget.share == 1.0


def test_a_spent_budget_stops_the_scan_and_says_how_far_it_got(sweep):
    occ, item, hint = _board(item_w=70.0)
    full = _scan(occ, item, hint, None)
    cut = _scan(occ, item, hint, 3000)
    assert cut.chosen is None and cut.tried == 3000 < full.tried
    assert cut.cut == {"judged": 3000, "limit": 3000, "share": pytest.approx(3000 / full.tried, abs=1e-4)}
    assert sum(cut.rejected.values()) == 3000


def test_a_spent_budget_takes_the_best_spot_found_so_far(sweep):
    occ, item, hint = _board()
    best = _scan(occ, item, hint, None, score=lambda cand: cand.location.x + 0.001 * cand.location.y)
    assert best.chosen is not None
    # the coarse pass alone is a sixteenth of the grid: spend just that
    coarse = placer._grid_offsets(12.0, 0.8)
    cut = _scan(occ, item, hint, len(coarse) * len(TURNS), score=lambda cand: cand.location.x + 0.001 * cand.location.y)
    assert cut.cut is not None and cut.chosen is not None
    assert cut.tried <= len(coarse) * len(TURNS) and cut.tried < best.tried


def test_a_budget_is_shared_by_the_scans_of_a_step(sweep):
    occ, item, hint = _board(item_w=70.0)
    occ.step_budget = placer.SearchBudget(5000)
    one = placer.scan(occ, item, hint, 12.0, 0.2, TURNS, None)
    two = placer.scan(occ, item, hint, 12.0, 0.2, TURNS, None)
    assert one.tried == 5000 and two.tried == 0
    assert two.cut["judged"] == 5000


def test_the_default_budget_is_a_setting(tmp_path):
    from placemat import settings as S
    assert Settings().place_step_budget >= 1
    (tmp_path / "placemat.toml").write_text("[place]\nstep_budget = 1234\n")
    assert S.load(tmp_path).place_step_budget == 1234
    (tmp_path / "placemat.toml").write_text("[place]\nstep_budget = 0\n")
    with pytest.raises(S.SettingsError):
        S.load(tmp_path)


def test_an_item_that_spends_its_budget_is_left_unplaced_with_the_measurement(tmp_path):
    board, plan, path = resolve(tmp_path, SEARCH % "budget=20")
    (f,) = [f for f in plan.findings if f.cause == "unplaced.search"]
    b = f.facts["budget"]
    assert b["limit"] == 20 and b["judged"] == 20 and 0 < b["share"] < 0.01
    assert "stopped at its budget of 20 candidates" in str(f)
    assert plan.placement("j1") is None


def test_the_same_search_without_the_budget_places_it(tmp_path):
    board, plan, path = resolve(tmp_path, SEARCH % "")
    assert plan.placement("j1") is not None
    assert not [f for f in plan.findings if f.cause in ("unplaced.search", "setup.step_budget")]


def test_the_setting_is_the_default_for_every_step(tmp_path):
    settings = dataclasses.replace(Settings(), place_step_budget=20)
    board, plan, path = resolve(tmp_path, SEARCH % "", settings=settings)
    (f,) = [f for f in plan.findings if f.cause == "unplaced.search"]
    assert f.facts["budget"]["limit"] == 20


def test_a_spent_budget_offers_a_higher_one_for_that_item(tmp_path):
    board, plan, path = resolve(tmp_path, SEARCH % "budget=20")
    (f,) = [f for f in plan.findings if f.cause == "unplaced.search"]
    s = next(s for s in f.suggestions if s.lever == "budget")
    assert s.how == "searched" and s.figure["declared"] == 20 and s.figure["far"] > 20
    assert s.figure["far"] >= f.facts["budget"]["judged"] / f.facts["budget"]["share"]
    assert s.edits[0].args["name"] == "budget" and s.edits[0].target.key == "j1"


def test_an_item_placed_at_the_best_spot_found_says_so(tmp_path):
    board, plan, path = resolve(tmp_path, SEARCH % "budget=300")
    (f,) = [f for f in plan.findings if f.cause == "setup.step_budget"]
    assert f.severity == "notice" and f.facts["limit"] == 300 and 0 < f.facts["share"] < 0.05
    assert plan.placement("j1") is not None and "best spot found" in str(f)
    assert next(s for s in f.suggestions if s.lever == "budget").figure["declared"] == 300


def test_budget_must_be_a_whole_number_of_at_least_one(tmp_path):
    for bad in ("budget=0", "budget=2.5", "budget=True", "budget='x'"):
        with pytest.raises(TypeError, match="budget="):
            resolve(tmp_path, SEARCH % bad)


def test_a_give_way_resolve_charges_the_budget_what_it_judged(monkeypatch):
    """A candidate whose carried vias give way is charged `Resolution.judged` (at least one), not one, so a step's budget
    counts the spots, tails and conflicts a via's move search put to the board."""
    import random
    from placemat import giveway
    from tests.scan_scenes import carried_vias_reachable, scene

    def run(occ, item, hint, rots, judged_of):
        spent = []

        def resolve(*a, **k):
            res = giveway.Resolution()
            res.judged = judged_of(len(spent))
            spent.append(res.judged)
            return res
        monkeypatch.setattr(giveway, "resolve", resolve)
        occ.step_budget = placer.SearchBudget(10 ** 9)
        placer.scan(occ, item, hint, 5.0, 0.25, rots, None, score=lambda c: c.location.x * 0.013 + c.location.y * 0.007,
                    pick=lambda ranked: ranked[0])
        return occ.step_budget.judged, spent

    rnd = random.Random(3)
    scenes = zero = many = 0
    for _ in range(40):
        occ, item, hint, rots = scene(rnd, cell=True, vias=True)
        if not carried_vias_reachable(occ, item, hint, 5.0):
            continue
        floor, _ = run(occ, item, hint, rots, lambda k: 0)
        charged, spent = run(occ, item, hint, rots, lambda k: 3 * (k % 5))
        assert charged - floor == sum(max(1, j) - 1 for j in spent)
        scenes += 1
        zero += spent.count(0)
        many += sum(j > 1 for j in spent)
    assert scenes >= 10 and zero >= 5 and many >= 20, (scenes, zero, many)
