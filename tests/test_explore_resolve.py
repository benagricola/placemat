"""A variant in Board.resolve(): seed 0 is the plain placement; any seed is
repeatable; only focused items vary; the steps before the first focused one
are replayed."""
from placemat.explore import Explore
from placemat.layout import Board
from placemat.values import LinkWeight, Location, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("U1", 10, 10, w=8, h=4, inst="mcu", nets=("A", "B")),
           footprint("R1", 60, 60, w=2, h=1, inst="r1", nets=("A", "X")),
           footprint("R2", 60, 62, w=2, h=1, inst="r2", nets=("B", "Y")),
           footprint("R3", 60, 64, w=2, h=1, inst="r3", nets=("A", "Z")),
           footprint("C1", 60, 66, w=2, h=1, inst="c1", nets=("B", "Q"))]
    b = Board(board_geometry(fps, width=50, height=50), edge_margin=1.0)
    b.place(Part("mcu"), at=Location(25, 25))
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
