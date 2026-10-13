"""A variant in Board.resolve(): seed 0 is the plain placement; any seed is
repeatable; only focused items vary; the steps before the first focused one
are replayed."""
from placemat.explore import Explore
from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


def _board(mcu=Location(25, 25)):
    fps = [footprint("U1", 10, 10, w=8, h=4, inst="mcu", nets=("A", "B")),
           footprint("R1", 60, 60, w=2, h=1, inst="r1", nets=("A", "X")),
           footprint("R2", 60, 62, w=2, h=1, inst="r2", nets=("B", "Y")),
           footprint("R3", 60, 64, w=2, h=1, inst="r3", nets=("A", "Z")),
           footprint("C1", 60, 66, w=2, h=1, inst="c1", nets=("B", "Q"))]
    b = Board(board_geometry(fps, width=50, height=50), edge_margin=1.0)
    b.place(Part("mcu"), at=mcu)
    for k in ("r1", "r2", "r3", "c1"):
        b.place(Part(k))
    return b


def _where(plan):
    return {s.item: (s.placement.location.x, s.placement.location.y, s.placement.rotation)
            for s in plan.steps if s.placement is not None and s.kind == "part"}


def test_seed_zero_is_the_plain_placement():
    assert _where(_board().resolve()) == _where(_board().resolve(explore=Explore(seed=0, focus=frozenset({"r1", "r2"}))))


def test_a_seed_is_repeatable():
    ex = Explore(seed=7, focus=frozenset({"r1", "r2", "r3", "c1"}))
    assert _where(_board().resolve(explore=ex)) == _where(_board().resolve(explore=ex))


def test_only_focused_items_vary():
    plain = _where(_board().resolve())
    for seed in range(1, 13):
        got = _where(_board().resolve(explore=Explore(seed=seed, focus=frozenset({"c1"}))))
        assert {k: v for k, v in got.items() if k != "c1"} == {k: v for k, v in plain.items() if k != "c1"}


def test_a_focused_item_takes_more_than_one_spot_across_seeds():
    spots = {_where(_board().resolve(explore=Explore(seed=s, focus=frozenset({"r1", "r2", "r3", "c1"}))))["r1"]
             for s in range(1, 33)}
    assert len(spots) > 1


def test_steps_before_the_first_focused_item_are_replayed():
    plain = _board().resolve()
    variant = _board().resolve(reuse=plain.reuse, explore=Explore(seed=5, focus=frozenset({"c1"})))
    order = [s.item for s in plain.steps if s.kind == "part"]
    assert variant.reuse["first_change"] == "c1"
    assert variant.reuse["reused"] >= order.index("c1")          # the fixed part and the searched ones before c1


def test_stale_baseline_and_variant_records_do_not_supply_plain_standing(monkeypatch):
    from placemat import reuse
    plain = _board().resolve()
    for bad in (dict(plain.reuse, version=reuse.VERSION - 1),
                dict(plain.reuse, explore_baseline_plain=False)):
        b = _board()
        original = b._resolve
        calls = []

        def resolve(*args, **kwargs):
            calls.append(args[2])
            return original(*args, **kwargs)

        monkeypatch.setattr(b, "_resolve", resolve)
        got = b.resolve(reuse=bad, explore=Explore(seed=5, focus=frozenset({"c1"})))
        assert calls[0] is None
        assert len(calls) == 2
        assert {k: v for k, v in _where(got).items() if k != "c1"} == {
            k: v for k, v in _where(plain).items() if k != "c1"}


def test_relative_searched_items_follow_the_focused_reference():
    import math
    from placemat.values import Near

    def board():
        fps = [footprint("R1", 20, 20, inst="r1", nets=("A", "X")),
               footprint("R2", 30, 30, inst="r2", nets=("A", "Y"))]
        b = Board(board_geometry(fps, width=50, height=50))
        b.place(Part("r1"), at=Near(Location(25, 25), radius=4, step=1), rotations=(0,))
        b.place(Part("r2"), at=Near(Part("r1"), radius=3, step=.5), rotations=(0,))
        return b

    plain = board().resolve()
    assert "r2" not in plain.reuse["explore_standing"]
    for seed in (1, 5, 9):
        got = _where(board().resolve(reuse=plain.reuse, explore=Explore(seed=seed, focus=frozenset({"r1"}))))
        assert math.dist(got["r1"][:2], got["r2"][:2]) <= 3 + 1e-9


def test_changed_declarations_replace_the_old_plain_standing():
    old = _board().resolve()
    new = _board(Location(35, 25)).resolve()
    got = _board(Location(35, 25)).resolve(reuse=old.reuse,
                                        explore=Explore(seed=5, focus=frozenset({"c1"})))
    held = lambda plan: {k: v for k, v in _where(plan).items() if k != "c1"}
    assert held(new) != held(old)
    assert held(got) == held(new)


def test_a_variant_binds_no_suggestions_and_the_plain_run_does(monkeypatch):
    """A variant is scored and compared, never shown or applied: its findings' suggestions are not bound to the script's
    lines (the script's AST work is a fifth of its resolve), and its placements are those it would have had."""
    from placemat import suggestions
    real = suggestions.bind
    calls = []
    monkeypatch.setattr(suggestions, "bind", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    ex = Explore(seed=7, focus=frozenset({"r1", "r2", "r3", "c1"}))
    variant = _where(_board().resolve(explore=ex))
    assert calls == []
    _board().resolve()
    assert calls == [1]
    monkeypatch.setattr(suggestions, "bind", real)
    assert variant == _where(_board().resolve(explore=ex))
