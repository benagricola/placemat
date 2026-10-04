"""A scan whose item carries vias that may give way judges each candidate twice: as the item is, then, where that refused it,
the item less its carried vias. What the second judgment refuses the first does too, so a full pass judges the item less
its vias first, over all, and the item as it is only where that was legal (`placer.B_FIRST`). The two orders give the same
scan: its spot, count, refusal tallies, first sentences and blockers, over random boards."""
import random

import pytest

from placemat import giveway, placer
from placemat.occupancy import Blocker
from placemat.refusals import Code, Refusal
from tests.scan_scenes import carried_vias_reachable, scene

pytestmark = pytest.mark.skipif(placer._geometry_module._native is None, reason="no native module")


def _summary(r, ranked):
    return (r.chosen, r.tried, dict(r.rejected), [(k, v.to_json()) for k, v in r.reasons.items()], dict(r.blockers), r.score,
            [(s, d, t, c) for s, d, t, c in ranked])


def _scan(occ, item, hint, rots, score, accept=None, radius=5.0):
    seen = []

    def pick(ranked):
        seen.extend(ranked)
        return ranked[0]
    r = placer.scan(occ, item, hint, radius, 0.25, rots, None, score=score, pick=pick, accept=accept)
    return _summary(r, seen)


def _resolve(occ, item, placement, clearance=None, others=None):
    """What giving way comes to, decided by where the candidate is: the vias' own search is not what is compared."""
    k = int(placement.location.x * 8) + int(placement.location.y * 8) + int(placement.rotation / 90)
    if k % 3 == 0:
        return giveway.Resolution(why=Refusal(Code.HOLE_TO_HOLE), blocker=Blocker("hole", "viacell", frozenset()))
    return giveway.Resolution(cost=0.25 * (k % 4))


@pytest.fixture(autouse=True)
def _vias_give_way_by_position(monkeypatch):
    monkeypatch.setattr(giveway, "resolve", _resolve)


def _score(cand):
    return round(cand.location.x * 0.013 + cand.location.y * 0.007 + cand.rotation * 1e-4, 6)


def _refuse_a_band(cand):
    from placemat.refusals import Code, Refusal
    return Refusal(Code.LOOKAHEAD_SPOT) if int(cand.location.x * 4) % 5 == 0 else None


@pytest.mark.parametrize("envelope", ["courtyard", "physical"])
@pytest.mark.parametrize("cell", [False, True], ids=["part", "cell"])
def test_judging_less_the_vias_first_and_once_scans_the_same(envelope, cell, monkeypatch):
    rnd = random.Random({"courtyard": 11, "physical": 23}[envelope] + cell)
    scenes = judged = 0
    for n in range(40):
        occ, item, hint, rots = scene(rnd, envelope=envelope, cell=cell, vias=True, reserve=rnd.random() < 0.5, ties=rnd.random() < 0.5)
        if not carried_vias_reachable(occ, item, hint, 5.0):
            continue
        scenes += 1
        for accept in (None, _refuse_a_band):
            runs = {}
            for first, once in ((False, False), (True, False), (False, True), (True, True)):
                monkeypatch.setattr(placer, "B_FIRST", first)
                monkeypatch.setattr(placer, "JUDGE_ONCE", once)
                runs[first, once] = _scan(occ, item, hint, rots, _score, accept)
            for how, run in runs.items():
                assert run == runs[False, False], ("scene %d" % n, how)
            judged += runs[True, True][1] > 0
    assert scenes >= 15 and judged >= 25, (scenes, judged)


def test_it_is_the_order_that_changes_not_what_is_judged(monkeypatch):
    """Judging less the vias first, each candidate a pass refuses is judged by one native call, not two."""
    rnd = random.Random(5)
    for _ in range(40):
        occ, item, hint, rots = scene(rnd, cell=True, vias=True)
        if carried_vias_reachable(occ, item, hint, 5.0):
            break
    from placemat import occupancy
    calls = {}
    real = occupancy.NativeSweeper._native_run

    def counting(self, triples, *a, **k):
        calls[id(self)] = calls.get(id(self), 0) + len(triples)
        return real(self, triples, *a, **k)
    monkeypatch.setattr(occupancy.NativeSweeper, "_native_run", counting)
    totals = {}
    for first in (False, True):
        calls.clear()
        monkeypatch.setattr(placer, "B_FIRST", first)
        placer.scan(occ, item, hint, 5.0, 0.25, rots, None, score=_score)
        totals[first] = sum(calls.values())
    assert totals[True] < totals[False], totals


def test_a_candidate_the_sweeper_judged_legal_less_its_vias_is_not_judged_again(monkeypatch):
    from placemat.occupancy import Occupancy
    rnd = random.Random(9)
    for _ in range(60):
        occ, item, hint, rots = scene(rnd, cell=True, vias=True, ties=True)
        if carried_vias_reachable(occ, item, hint, 5.0):
            break
    calls = []
    real = Occupancy.legal_bucket
    monkeypatch.setattr(Occupancy, "legal_bucket", lambda self, *a, **k: calls.append(1) or real(self, *a, **k))
    totals = {}
    for once in (False, True):
        calls.clear()
        monkeypatch.setattr(placer, "JUDGE_ONCE", once)
        placer.scan(occ, item, hint, 5.0, 0.25, rots, None, score=_score)
        totals[once] = len(calls)
    assert totals[True] < totals[False], totals         # none at all, where the native pass judges the net ties too
