"""A seeded item whose scan finds nothing takes the nearest pocket. Pure."""
import dataclasses

import placemat.layout as layout
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Location, Near, Part
from tests.fixtures import board_geometry, footprint


def _board(u_w=6.0, u_h=6.0, solve=False):
    """j1 on the west edge; a wall east of it leaves no room for u1 near j1.
    Past the wall a narrow gap, a second wall, then a wide gap."""
    fps = [footprint("J1", 3, 10, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("K1", 13, 10, w=16, h=17, inst="k1", nets=("K1A", "K1B")),
           footprint("K2", 35, 10, w=10, h=17, inst="k2", nets=("K2A", "K2B")),
           footprint("U1", 50, 10, w=u_w, h=u_h, inst="u1", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=60, height=20), edge_margin=0.5, keep_going=True,
              settings=dataclasses.replace(Settings(), solve_enabled=solve))
    b.place(Part("j1"), at=Location(3, 10))
    b.place(Part("k1"), at=Location(13, 10))
    b.place(Part("k2"), at=Location(35, 10))
    return b


def _step(plan, key):
    return next(s for s in plan.steps if s.item == key)


def test_a_seeded_part_with_no_room_by_its_connections_takes_a_pocket():
    b = _board()
    b.place(Part("u1"))
    plan = b.resolve()
    s = _step(plan, "u1")
    assert s.placement is not None
    assert "took the pocket" in s.note and "mm from the seed" in s.note
    assert "seeded on A, but no legal spot within 6.0 mm" in s.note
    assert not [f for f in plan.findings if f.startswith("u1")]
    assert plan.pocketed == ["u1"]


def test_the_pocket_nearer_the_seed_wins_over_a_bigger_one():
    b = _board()
    b.place(Part("u1"))
    x = _step(b.resolve(), "u1").placement.location.x
    assert 21.0 < x < 30.0, x


def test_an_explicit_near_that_fails_stays_unplaced():
    b = _board()
    b.place(Part("u1"), at=Near(Location(3, 15)))
    plan = b.resolve()
    s = _step(plan, "u1")
    assert s.placement is None and "UNPLACED" in s.note
    assert any(f.startswith("u1: no legal location within") for f in plan.findings)
    assert plan.pocketed == []


def test_with_no_pocket_the_part_is_unplaced_and_the_finding_says_so(monkeypatch):
    """The earlier "no pocket fits" check reads pockets() too; it is switched
    off so this reaches the case where pockets fit but none takes the part."""
    monkeypatch.setattr(layout, "pockets", lambda *a, **k: [])
    monkeypatch.setattr(Board, "_no_pocket_note", lambda self, occ, i: "")
    b = _board()
    b.place(Part("u1"))
    plan = b.resolve()
    assert _step(plan, "u1").placement is None
    assert any(f.startswith("u1: no legal location within") and f.endswith("; no pocket took it (0 tried)")
               for f in plan.findings)


def test_a_dropped_solve_hint_then_a_failed_seed_ends_in_a_pocket(monkeypatch):
    monkeypatch.setattr(Board, "_global_hints", lambda self, occ, placed, plan: {"u1": Location(10, 10)})
    b = _board(solve=True)
    b.place(Part("u1"))
    s = _step(b.resolve(), "u1")
    assert s.placement is not None
    assert "global solve's hint" in s.note and "took the pocket" in s.note


def test_a_seeded_part_that_fits_by_its_connections_is_where_it_was():
    """No wall: the seeded scan succeeds and the fallback never runs."""
    fps = [footprint("J1", 3, 10, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("U1", 50, 10, w=6, h=6, inst="u1", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=60, height=20), edge_margin=0.5)
    b.place(Part("j1"), at=Location(3, 10))
    b.place(Part("u1"))
    plan = b.resolve()
    assert "pocket" not in _step(plan, "u1").note and plan.pocketed == []


def test_a_searched_steps_note_gives_its_rank_once():
    b = _board()
    b.place(Part("u1"))
    note = _step(b.resolve(), "u1").note
    assert note.count("rank 1/1") == 1, note


def test_the_run_metrics_count_pocketed_items():
    from placemat.runner import run_metrics
    b = _board()
    b.place(Part("u1"))
    plan = b.resolve()
    m = run_metrics(plan, 4, 0, {})
    assert m["pocketed"] == 1
    assert m["placed"] == 4 and m["findings"] == len(plan.findings)
