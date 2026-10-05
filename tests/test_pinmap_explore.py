"""At the end of an explore the pin map study runs on the best `pins.explore_top` variants: each variant's crossings
after remapping and its map are reported beside its run score, which they do not change."""
from types import SimpleNamespace

from placemat import pinmap
from placemat.explore import _pin_maps, _report_lines, pin_map_lines, search
from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint
from tests.pinmap_boards import quad_footprint, settings
from tests.test_pinmap_wiring import board

RESULT = SimpleNamespace(results=[(0, 10.0, {}), (2, 11.0, {}), (5, 12.5, {}), (7, 13.0, {})])


def test_the_best_variants_are_studied_in_the_explores_order_and_reported_beside_their_score():
    b = board()
    made = []

    def make():
        made.append(1)
        return board()
    maps = _pin_maps(make, [], frozenset({"r1"}), RESULT, {0: (b, b.resolve())})
    assert [(m["seed"], m["score"]) for m in maps] == [(0, 10.0), (2, 11.0), (5, 12.5)] and len(made) == 2
    (g,) = maps[0]["groups"]
    assert g["refs"] == ["U1"] and g["best"]["weighted"] < g["present"]["weighted"] and g["map"]
    report = {"tried": 4, "seconds": 1.0, "focus": ["r1"], "baseline": 10.0, "best": 10.0, "best_seed": 2,
              "moves": [], "accepted": False, "pin_maps": maps}
    lines = _report_lines(report)
    assert "  pin map, seed 2 at 11.0 mm: U1 6 -> 0 weighted crossings after remapping" in lines
    assert lines[0].endswith("score 10.0 -> 10.0 mm; 0 items would move")


def test_a_board_without_a_pool_resolves_no_variant_for_the_study():
    b = board(fields={})
    made = []
    assert _pin_maps(lambda: made.append(1), [], frozenset(), RESULT, {0: (b, b.resolve())}) == [] and made == []


def test_a_study_that_raises_on_a_variant_leaves_the_others_and_says_so_on_its_line(monkeypatch):
    b = board()
    real = pinmap.plan_summary

    def summary(board_, plan, refs=None, settings=None):
        if board_ is not b:
            raise RuntimeError("boom")
        return real(board_, plan, refs, settings)
    monkeypatch.setattr(pinmap, "plan_summary", summary)
    maps = _pin_maps(board, [], frozenset({"r1"}), RESULT, {0: (b, b.resolve())})
    assert [m["seed"] for m in maps] == [0, 2, 5] and maps[0]["groups"] and "error" not in maps[0]
    assert maps[1] == {"seed": 2, "score": 11.0, "groups": [], "error": {"type": "RuntimeError", "message": "boom"}}
    lines = pin_map_lines({"pin_maps": maps})
    assert "  pin map, seed 2 at 11.0 mm: the study failed with RuntimeError: boom" in lines
    assert len(lines) == 3


def _searched_board():
    """The pool board, its resistors searched: an explore has something to move."""
    fps = [quad_footprint("U1", 10, 10, {"E": ["A", "B", "C", "D"]}, {"Pm.PinPool": "1-4"})]
    for i, net in enumerate(["D", "C", "B", "A"]):
        fps.append(footprint("R%d" % (i + 1), 60, 60 + 2 * i, w=2, h=1, inst="r%d" % (i + 1), nets=(net, "G%d" % i)))
    b = Board(board_geometry(fps, width=40, height=30), edge_margin=1.0, settings=settings(pins_rotations=(0.0,)))
    b.place(Part("u1"), at=Location(10, 10))
    for i in range(4):
        b.place(Part("r%d" % (i + 1)))
    return b


def test_an_explore_reports_the_study_of_its_best_variant_first(tmp_path):
    report, _ = search(_searched_board, tmp_path / "Board_layout.py", seconds=60, jobs=1, seeds=range(0, 4))
    maps = report["pin_maps"]
    assert len(maps) == 3 and maps[0]["seed"] == report["best_seed"] and maps[0]["score"] == round(report["best"], 1)
    assert all(m["groups"] and m["groups"][0]["refs"] == ["U1"] for m in maps)


# seeds 0-7 of `_searched_board` rank 2, 6, 5 first: the best is not seed 0, and the other two are resolved again
SEEDS = range(0, 8)


class _Counting:
    """`_searched_board`, counting the boards made in this process (a worker counts its own)."""

    def __init__(self):
        self.made = 0

    def __call__(self):
        self.made += 1
        return _searched_board()


def _spied(monkeypatch, make=None):
    from placemat import explore
    calls = []
    real = explore._pin_maps

    def spy(make_board, entries, focus, result, have):
        before = make.made if make else 0
        out = real(make_board, entries, focus, result, have)
        calls.append({"entries": list(entries), "seeds": sorted(have), "made": (make.made if make else 0) - before})
        return out
    monkeypatch.setattr(explore, "_pin_maps", spy)
    return calls


def test_the_best_variant_is_studied_on_the_plan_the_search_resolved_for_it(tmp_path, monkeypatch):
    make = _Counting()
    calls = _spied(monkeypatch, make)
    report, _ = search(make, tmp_path / "Board_layout.py", seconds=60, jobs=1, seeds=SEEDS)
    assert report["best_seed"] == 2 and [m["seed"] for m in report["pin_maps"]] == [2, 6, 5]
    assert calls == [{"entries": [], "seeds": [0, 2], "made": 2}]


def test_with_accept_the_variants_are_studied_under_the_lock_they_were_ranked_under(tmp_path, monkeypatch):
    from placemat import lock
    script = tmp_path / "Board_layout.py"
    calls = _spied(monkeypatch)
    report, entries = search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS, accept=True)
    assert report["accepted"] and entries and lock.path_for(script).exists()
    assert [c["entries"] for c in calls] == [[]]
    assert [m["seed"] for m in report["pin_maps"]] == [2, 6, 5]


def test_pins_explore_top_sets_how_many_variants_are_studied():
    from dataclasses import replace
    for top, seeds, resolved in ((0, [], 0), (1, [0], 0), (2, [0, 2], 1)):
        b = board()
        b.settings = replace(b.settings, pins_explore_top=top)
        made = []

        def make():
            made.append(1)
            return board()
        maps = _pin_maps(make, [], frozenset({"r1"}), RESULT, {0: (b, b.resolve())})
        assert [m["seed"] for m in maps] == seeds and len(made) == resolved


def test_a_stop_during_the_study_stops_the_explore_with_its_report_and_accepts_nothing(tmp_path, monkeypatch):
    import signal
    import pytest
    from placemat import lock, stop

    def stopped(*a, **kw):
        raise stop.Stopped(signal.SIGTERM)
    monkeypatch.setattr(pinmap, "plan_summary", stopped)
    script = tmp_path / "Board_layout.py"
    with pytest.raises(stop.Stopped) as e:
        search(_searched_board, script, seconds=60, jobs=1, seeds=SEEDS, accept=True)
    r = e.value.explore
    assert e.value.stage == "explore" and r["stopped"] == "SIGTERM" and r["best_seed"] == 2 and not r["accepted"]
    assert "pin_maps" not in r and not lock.path_for(script).exists()
