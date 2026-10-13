"""A pad that the script's declared copper will join has a way out before that copper is laid, as it has once the copper
is laid (D28): the search, the retry, cleanup and the turn check judge it as the finished board does. U9's pad is walled
in by N1's ring of pads but for a slit; a track through the slit joins it to N1's pad of its net."""
import dataclasses

import pytest

from placemat import escapes, prepared_escape
from placemat import layout as layout_module
from placemat.board_geometry import Footprint
from placemat.layout import Board
from placemat.score_search import MSTScorer
from placemat.settings import Settings
from placemat.values import CopperLayer, Face, Net, PadRef, Part
from tests.conftest import needs_native
from tests.fixtures import footprint
from tests.fixtures import board_geometry
from tests.test_escape_walled_joined import _parts

F = CopperLayer.F
U9 = ("U9", "GND")


def _board(track: bool, **settings):
    """U9 and N1 where `_parts` puts them, X1 just east of N1 on N1's ring net (it holds N1 where it stands), and T1 far
    off; with `track`, U9's pad joined to N1's by a declared track."""
    fps = _parts() + [footprint("X1", 36.5, 30, inst="x1", nets=("SIG", "Z")),
                      footprint("T1", 50, 50, inst="t1", nets=("X", "Y"))]
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False, **settings)
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, settings=cfg, keep_going=True)
    for fp in fps:
        b.place(Part(fp.inst), at=fp.location)
    if track:
        b.track(Net("GND"), [PadRef(Part("u9"), "GND"), PadRef(Part("n1"), "GND")], layer=F, why="joins U9's pad")
    return b


def _walled(occ) -> list:
    return sorted((r, n) for r, n, *_ in escapes.Escapes(occ).found()["escape_walled"])


def _fp(board, ref) -> Footprint:
    return next(fp for fp in board.geometry.footprints if fp.ref == ref)


def test_the_pads_a_declared_track_will_join_are_not_walled_before_it_is_laid(monkeypatch):
    seen = {}
    real = Board._plan_copper

    def plan_copper(self, occ, ctx, intents, plan, progress, slot=None):
        if slot == "fixed":
            seen["planned"] = occ.planned_joins
            seen["walled"] = _walled(occ)
            occ.planned_joins, kept = frozenset(), occ.planned_joins
            seen["without"] = _walled(occ)
            occ.planned_joins = kept
        return real(self, occ, ctx, intents, plan, progress, slot=slot)
    monkeypatch.setattr(Board, "_plan_copper", plan_copper)
    plan = _board(True).resolve()
    assert seen["planned"] == {U9, ("N1", "GND")}
    assert seen["without"] == [U9], "fixture: before the track is laid, U9's pad is walled in by N1's ring"
    assert seen["walled"] == []
    # the finished board: the track is laid, nothing is planned, and the pad is joined by the copper itself
    assert plan.occupancy.planned_joins == frozenset()
    assert any(c.kind == "copper" and c.net == "GND" for c in plan.occupancy.copper)
    assert _walled(plan.occupancy) == []


def test_only_copper_drawn_onto_the_pad_counts():
    """A pad reference with an offset, a via off the pad and a pour are not drawn onto the pad at the pad."""
    from placemat.values import FreeSpot
    b = _board(False)
    b.track(Net("GND"), [PadRef(Part("u9"), "GND", dx=1.0), PadRef(Part("n1"), "GND", dx=0.5)], layer=F)
    off = b.via(Net("GND"), FreeSpot(PadRef(Part("n1"), "GND"), tail=False))
    at = b.via(Net("GND"), PadRef(Part("u9"), "GND"))
    tailed = b.via(Net("GND"), FreeSpot(PadRef(Part("n1"), "GND")))
    assert b._copper[0].joins == ()
    assert off.joins == ()
    assert at.joins == (U9,)
    assert tailed.joins == (("N1", "GND"),)


def _scores(board, plan, ref, planned, native_memo=True):
    """(walled base, Python (walled, cost), native (walled, cost)) of `ref` lifted and scored at its own spot, with
    `planned` as the pads planned copper will join."""
    occ = plan.occupancy
    occ.planned_joins = frozenset(planned)
    fp = _fp(board, ref)
    pose = occ.items[ref].reference
    occ.lift({ref})
    prepared_escape.NATIVE_MEMO = native_memo
    try:
        scorer = MSTScorer(board, occ, fp, plan=plan)
        assert scorer.native((pose.rotation,), pose.face) is not None, scorer.refusals
        out = scorer.walled_base, scorer(pose), scorer.full(pose)
    finally:
        prepared_escape.NATIVE_MEMO = True
        occ.unlift({ref})
    return out


@needs_native
@pytest.mark.parametrize("ref", ["T1", "N1", "U9"])
def test_python_and_native_judge_a_planned_join_alike_with_and_without_the_memos(monkeypatch, ref):
    """T1 lifted: U9's pad is a rest pad (the baseline memo, the native rest cache). N1 lifted: the candidate walls it.
    U9 lifted: it is the candidate's own pad. Each judged with and without the planned join, the memos kept from one
    lifted board to the next, against a judgement with no memo."""
    board = _board(False)
    plan = board.resolve()
    assert _walled(plan.occupancy) == [U9], "fixture"
    runs = [(), (U9,), (), (U9,)]
    got = [_scores(board, plan, ref, p) for p in runs]
    monkeypatch.setattr(escapes, "BASELINE_MEMO", False)
    fresh = [_scores(board, plan, ref, p, native_memo=False) for p in runs]
    assert got == fresh
    for planned, (base, python, native) in zip(runs, got):
        walled = 0 if planned else 1
        assert python[0] == native[0] == walled, (planned, python, native)
        assert python[1] == pytest.approx(native[1], abs=1e-9)
        assert base == (walled if ref == "T1" else 0)


def _ring_part_movable():
    """`_board(False)` with N1, whose ring walls U9's pad, left to cleanup: (board, plan, N1's footprint)."""
    board = _board(False, score_congestion=0.0)
    plan = board.resolve()
    return board, plan, _fp(board, "N1")


@pytest.mark.parametrize("planned", [False, True])
def test_cleanup_pays_no_run_score_to_unwall_a_pad_planned_copper_will_join(planned):
    from placemat import score
    from placemat.cleanup import cleanup
    board, plan, n1 = _ring_part_movable()
    occ = plan.occupancy
    occ.planned_joins = frozenset({U9} if planned else ())
    spot = occ.items["N1"].reference
    before = sum(score.whole(board, occ, plan).values())
    one_score = lambda fp: MSTScorer(board, occ, fp, plan=plan, prune=True)      # noqa: E731
    pins = {"GND": [U9, ("N1", "GND")]}
    cleanup(occ, {"n1": n1}, pins, [], board.clearance, 2, 10.0, 0.5, settings=board.settings, one_score=one_score)
    after = sum(score.whole(board, occ, plan).values())
    if planned:
        assert occ.items["N1"].reference == spot
        assert after == pytest.approx(before)
    else:
        # fixture: with the pad counted walled, the move that unwalls it is taken at a higher run score
        assert occ.items["N1"].reference != spot and after > before
        assert _walled(occ) == []
