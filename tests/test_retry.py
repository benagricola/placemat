"""D27: after the searched tier, an item the one-score search left unplaced for want of room is tried again, the
placed items in the way of a room lifted and placed again after it (retry.py). Synthetic boards: a corner room (R1)
by the part both items pull to, and a strip (R2) beyond a wall that only the flat item fits."""
import dataclasses

from placemat import retry, score
from placemat.board_geometry import members_of
from placemat.layout import Board, _RetryHost
from placemat.settings import Settings
from placemat.values import Cell, Location, Part, Priority
from tests.fixtures import board_geometry, footprint


def _board(strip: float = 5.0, a_size=(13.0, 17.0), rounds: int = 2, cell: bool = False, fanout=()):
    """F sits in R1's corner and pulls B (flat, placed first) and A (tall) to it. A fits R1 only when B is elsewhere;
    B fits R1 or the strip R2, `strip` mm tall. With `cell`, B is a cell of two parts side by side."""
    fps = [footprint("F", 1.5, 1.2, w=1.0, h=0.8, inst="f", nets=("SB", "SA")),
           footprint("W1", 15.0, 10.0, w=1.2, h=18.6, inst="w1", nets=("G1", "G2")),
           footprint("W2", 27.5, (0.5 + strip + 19.3) / 2, w=22.6, h=19.3 - 0.5 - strip, inst="w2",
                     nets=("G3", "G4")),
           footprint("A", 30.0, 10.0, w=a_size[0], h=a_size[1], inst="a", nets=("SA", "GA"))]
    if cell:
        fps += [footprint("B1", 27.0, 3.0, w=6.0, h=3.0, inst="b1", nets=("SB", "GB"), cell="b"),
                footprint("B2", 33.0, 3.0, w=6.0, h=3.0, inst="b2", nets=("GB", "GC"), cell="b")]
    else:
        fps.append(footprint("B", 30.0, 3.0, w=12.0, h=3.0, inst="b", nets=("SB", "GB")))
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False, place_retry_rounds=rounds)
    board = Board(board_geometry(fps, cells=("b",) if cell else (), width=40, height=20), edge_margin=0.5,
                  settings=cfg)
    board.rect(width=40, height=20)
    for fp in fps[:3]:
        board.place(Part(fp.inst), at=fp.location)
    board.place(Cell("b") if cell else Part("b"), priority=Priority.HIGH)
    board.place(Part("a"))
    for k in fanout:
        board.fanout(Part(k), depth=1.0)
    return board


def _retries(plan):
    return [s for s in plan.steps if s.kind == "retry"]


def test_a_placed_item_in_the_room_a_later_one_needs_is_lifted_and_both_are_placed():
    plan = _board(rounds=0).resolve()
    assert plan.step("b").placement is not None and plan.step("a").placement is None, \
        "fixture: B, placed first, takes the room A needs"
    plan = _board().resolve()
    a, b = plan.step("a").placement, plan.step("b").placement
    assert a is not None and b is not None
    assert b.location.x > 15.0, "B went to the strip beyond the wall"
    kept = [r for r in plan.retry if r["kept"]]
    assert [(r["item"], r["lifted"], r["placed"]) for r in kept] == [("a", ["b"], ["a", "b"])]
    assert _retries(plan) and _retries(plan)[-1].notes[0]["kind"] == "retry"
    assert not [f for f in plan.findings if f.facts.get("item") == "a" and f.kind == "unplaced"], \
        "A's unplaced finding went with its old step"


def _state(board, plan):
    occ = plan.occupancy
    return ({k: v for k, v in occ.items.items()}, set(occ.pending), list(occ.copper), list(occ.reservations),
            dict(occ.given_way), dict(occ._cell_rule_areas), dict(occ._cell_fill_areas), dict(occ.fill_areas),
            [(s.item, s.placement, s.notes, s.unplaced) for s in plan.steps], list(plan.findings), dict(plan.turns),
            dict(plan.seeded_by_net), list(plan.pocketed), dict(board._step_found), dict(board._cell_placements),
            score.whole(board, occ, plan))


def _undone(cell: bool):
    """The strip is too narrow for B: placing A in R1 leaves B, of higher priority, unplaced, so the try is undone and
    the board is as it was."""
    board = _board(strip=2.0, rounds=0, cell=cell)
    plan = board.resolve()
    assert plan.step("a").placement is None
    occ = plan.occupancy
    placed = {fp.ref for s in plan.steps if s.placement is not None for fp in members_of(plan._items[s.item])}
    host = _RetryHost(board, occ, plan, placed)
    assert host.unplaced() == ["a"]
    rooms = host.rooms("a", 4, 2)
    assert rooms and rooms[0].lifted == ("b",)
    before = _state(board, plan)
    rec = retry.attempt(host, "a", rooms[0].lifted, 0, rooms[0].at)
    assert rec["placed"] == ["a"] and not rec["kept"]
    assert rec["after"]["unplaced"][0] == len(members_of(plan._items["b"])) and rec["before"]["unplaced"][0] == 0
    after = _state(board, plan)
    assert after[0].keys() == before[0].keys() and all(after[0][k] is before[0][k] for k in before[0])
    assert after[1:-1] == before[1:-1]
    assert after[-1] == before[-1], "the ratsnest, escapes and congestion read the board as before"


def test_a_try_that_would_lose_a_placed_part_is_undone_and_the_board_is_as_it_was():
    _undone(cell=False)


def test_a_try_that_lifts_a_cell_and_would_lose_it_is_undone_and_the_board_is_as_it_was():
    _undone(cell=True)


def test_the_retry_records_an_undone_try_and_leaves_the_board_unchanged():
    plain = _board(strip=2.0, rounds=0).resolve()
    tried = _board(strip=2.0).resolve()
    assert tried.retry and not any(r["kept"] for r in tried.retry)
    assert [(s.item, s.placement) for s in tried.steps if s.kind != "retry"] == \
        [(s.item, s.placement) for s in plain.steps]


def test_an_item_no_position_on_the_board_takes_is_not_retried(monkeypatch):
    """A is wider than the board: its refusals say no pocket took it, but that is not for want of room, so it is not
    tried and no room is looked for."""
    asked = []
    monkeypatch.setattr(retry, "rooms", lambda *a, **k: asked.append(a) or [])
    board = _board(a_size=(45.0, 3.0))
    plan = board.resolve()
    assert plan.step("a").placement is None
    assert plan.retry == [] and not _retries(plan) and not asked
    placed = {fp.ref for s in plan.steps if s.placement is not None for fp in members_of(plan._items[s.item])}
    assert _RetryHost(board, plan.occupancy, plan, placed).unplaced() == []


def test_a_part_with_a_fanout_is_neither_lifted_nor_tried_again():
    """Its fanout's bands were reserved where it was first placed: moving it would leave them behind."""
    plan = _board(fanout=("b",)).resolve()
    assert plan.step("a").placement is None
    assert not [r for r in plan.retry if "b" in r["lifted"]]
    plan = _board(fanout=("a",)).resolve()
    assert plan.step("a").placement is None and plan.retry == []
