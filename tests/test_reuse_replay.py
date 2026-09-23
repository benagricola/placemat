"""Replaying the previous run's steps inside a resolve. Pure: synthetic boards."""
import dataclasses

from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Location, Part, Priority
from tests.fixtures import board_geometry, footprint


def _fps():
    return [footprint("J1", 5, 10, inst="j1", nets=("A", "GND")),
            footprint("U1", 20, 10, w=6, h=3, inst="ldo", nets=("VIN", "VOUT")),
            footprint("C1", 50, 5, inst="cin", nets=("VIN", "GND")),
            footprint("R1", 25, 15, inst="r1", nets=("A", "B")),
            footprint("R2", 30, 12, inst="r2", nets=("B", "C")),
            footprint("R3", 35, 5, inst="r3", nets=("C", "VOUT"))]


def _board(r2_radius=3.0, r3_priority=None, block=False, **settings):
    b = Board(board_geometry(_fps(), width=60, height=30), edge_margin=0.5, keep_going=True,
              settings=dataclasses.replace(Settings(), **settings))
    b.place(Part("j1"), at=Location(5, 10))
    if block:
        b.place(b.block(Part("ldo"), satellites=[(Part("cin"), "VIN")], gap=0.5))
    else:
        b.place(Part("ldo"))
        b.place(Part("cin"))
    b.place(Part("r1"))
    b.place(Part("r2"), radius=r2_radius)
    b.place(Part("r3"), priority=r3_priority)
    return b


def _same(a, b):
    """Two plans that say and hold the same."""
    assert [(s.item, s.kind, s.placement, s.note, s.moved_mm, s.rank) for s in a.steps] == \
           [(s.item, s.kind, s.placement, s.note, s.moved_mm, s.rank) for s in b.steps]
    assert a.findings == b.findings and a.pocketed == b.pocketed and dict(a.seeded_by_net) == dict(b.seeded_by_net)
    assert a.cleanup == b.cleanup
    assert {r: g.reference for r, g in a.occupancy.items.items()} == {r: g.reference for r, g in b.occupancy.items.items()}


def test_resolving_again_with_nothing_changed_replays_every_step():
    first = _board().resolve()
    again = _board().resolve(reuse=first.reuse)
    _same(first, again)
    assert again.reuse["reused"] == len(first.reuse["steps"]) and again.reuse["first_change"] is None


def test_a_changed_item_replays_the_steps_before_it_and_matches_a_fresh_run_after():
    first = _board().resolve()
    fresh = _board(r2_radius=6.0).resolve()
    again = _board(r2_radius=6.0).resolve(reuse=first.reuse)
    _same(fresh, again)
    assert 0 < again.reuse["reused"] < len(first.reuse["steps"]) and again.reuse["first_change"] == "r2"


def test_a_changed_order_breaks_the_chain_where_it_changes():
    first = _board().resolve()
    fresh = _board(r3_priority=Priority.HIGH).resolve()
    again = _board(r3_priority=Priority.HIGH).resolve(reuse=first.reuse)
    _same(fresh, again)
    assert again.reuse["first_change"] is not None and again.reuse["reused"] < len(first.reuse["steps"])


def test_a_block_replays_with_its_satellites_where_a_fresh_run_puts_them():
    first = _board(block=True).resolve()
    again = _board(block=True).resolve(reuse=first.reuse)
    _same(first, again)
    assert again.reuse["reused"] == len(first.reuse["steps"])


def test_a_record_from_another_context_replays_nothing():
    first = _board().resolve()
    again = _board(place_step=0.1).resolve(reuse=first.reuse)
    assert again.reuse["reused"] == 0
    _same(_board(place_step=0.1).resolve(), again)


def test_the_cleanup_is_replayed_when_every_step_was(monkeypatch):
    import placemat.cleanup as cleanup_module
    first = _board().resolve()
    assert first.cleanup                                   # the pass ran and did something to record
    def never(*a, **k):
        raise AssertionError("the cleanup ran again though nothing changed")
    monkeypatch.setattr(cleanup_module, "cleanup", never)
    again = _board().resolve(reuse=first.reuse)
    _same(first, again)


def test_the_cleanup_runs_when_a_step_was_resolved():
    first = _board().resolve()
    again = _board(r2_radius=6.0).resolve(reuse=first.reuse)
    _same(_board(r2_radius=6.0).resolve(), again)
