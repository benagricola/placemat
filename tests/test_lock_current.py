"""`placemat lock <script> --current`: every searched item locked where the
board stands, once its resolve is seen to land there."""
from placemat import lock
from placemat.values import Part
from tests.test_lock import FOCUS, _board, _where


def _pads_of(plan):
    """{(instance, pad): (x, y)} of every placed part: the written board, as
    this plan would write it."""
    out = {}
    for fp in plan.geometry.footprints:
        g = plan.occupancy.items.get(fp.ref)
        if g is None:
            continue
        for p in fp.pads:
            at = plan.occupancy.pad_location(fp.ref, p.number)
            out[(fp.inst, p.number)] = (at.x, at.y)
    return out


def test_every_searched_item_is_locked_where_it_stands():
    b = _board()
    plan = b.resolve()
    entries, locked, refused = lock.current(b, plan, _pads_of(plan), [], 0.001)
    assert set(locked) == FOCUS and not refused
    again = _board().resolve(lock=entries)
    assert _where(again) == _where(plan)
    assert all("held by lock" in s.note for s in again.steps if s.item in FOCUS)


def test_an_item_that_would_not_land_where_the_board_has_it_is_named_and_not_locked():
    b = _board()
    plan = b.resolve()
    written = _pads_of(plan)
    written[("r2", "1")] = (written[("r2", "1")][0] + 0.5, written[("r2", "1")][1])     # r2 stands elsewhere
    entries, locked, refused = lock.current(b, plan, written, [], 0.001)
    assert "r2" in refused and "r2" not in locked and "r1" in locked
    assert "on the board" in refused["r2"]


def test_the_lock_keeps_the_entries_it_was_not_asked_about():
    b = _board()
    plan = b.resolve()
    kept = lock.LockEntry("elsewhere", None, None, (1.0, 2.0), 0.0, "front", "x")
    entries, _, _ = lock.current(b, plan, _pads_of(plan), [kept], 0.001)
    assert "elsewhere" in {e.key for e in entries} and FOCUS <= {e.key for e in entries}


def test_only_the_keys_asked_for_are_locked():
    b = _board()
    plan = b.resolve()
    entries, locked, _ = lock.current(b, plan, _pads_of(plan), [], 0.001, keys={"r1"})
    assert locked == ["r1"] and {e.key for e in entries} == {"r1"}


def _cleanup_board():
    from tests.test_cleanup_wiring import _board as cleanup_board
    b = cleanup_board(True)
    b.place(Part("r1"))
    b.place(Part("r2"))
    return b


def test_an_item_the_cleanup_moved_is_locked_where_the_cleanup_left_it():
    b = _cleanup_board()
    plan = b.resolve()
    assert any("cleanup" in (s.note or "") for s in plan.steps)          # the board this is about
    written = _pads_of(plan)
    entries, locked, refused = lock.current(b, plan, written, [], 0.001)
    assert set(locked) == {"r1", "r2"} and not refused
    again = _pads_of(_cleanup_board().resolve(lock=entries))
    assert all(abs(a - b) < 1e-6 for k in written for a, b in zip(written[k], again[k]))


def test_locking_one_item_locks_the_items_it_is_anchored_on():
    b = _cleanup_board()
    plan = b.resolve()
    written = _pads_of(plan)
    anchor = plan.turns["r2"]["anchor"]
    entries, locked, refused = lock.current(b, plan, written, [], 0.001, keys={"r2"})
    assert "r2" in locked and not refused
    if anchor is not None and anchor[0] == "R1":
        assert "r1" in locked
    again = _cleanup_board().resolve(lock=entries)
    for k in (("r2", "1"), ("r2", "2")):
        assert all(abs(a - b) < 1e-6 for a, b in zip(written[k], _pads_of(again)[k]))
