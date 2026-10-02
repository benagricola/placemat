"""What the studio hooks into a resolve: the step callback and where an item was declared."""
from pathlib import Path

from placemat.layout import Board
from placemat.values import Face, Location, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("J1", 3, 10, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("U1", 30, 10, w=6, h=6, inst="u1", nets=("A", "B")),
           footprint("R1", 40, 15, w=2, h=1, inst="r1", nets=("B", "C"), face=Face.BACK),
           footprint("C1", 20, 5, w=2, h=1, inst="c1", nets=("B", "GND"))]
    b = Board(board_geometry(fps, width=60, height=20), edge_margin=0.5, keep_going=True)
    b.place(Part("j1"), at=Location(3, 10))
    b.place(Part("u1"))
    b.place(Part("r1"), face=Face.BACK)
    b.place(Part("c1"))
    b.link(PadRef(Part("u1"), 1), PadRef(Part("j1"), 1), limit_mm=20.0)
    return b


def _summary(plan):
    return ([(s.item, s.kind, s.placement, s.note) for s in plan.steps], list(plan.findings), len(plan.copper))


def test_a_step_callback_changes_nothing_and_sees_each_placed_item_once_in_order():
    seen = []
    plain = _board().resolve()
    watched = _board().resolve(on_step=lambda plan, step: seen.append((step.item, len(plan.steps))))
    assert _summary(plain) == _summary(watched)
    assert [k for k, _ in seen] == [s.item for s in watched.steps if s.kind == "part"]
    assert [n for _, n in seen] == sorted(n for _, n in seen)


def test_the_callback_sees_the_item_already_in_the_occupancy():
    def check(plan, step):
        if step.placement is not None:
            assert plan.occupancy.items[plan._items[step.item].ref].body is not None
    _board().resolve(on_step=check)


def test_an_item_knows_the_file_and_line_that_declared_it():
    b = _board()
    mine = {i.key: i for i in b._intents}
    assert Path(mine["u1"].file).name == "test_studio_hooks.py"
    assert mine["u1"].line > 0
    assert mine["c1"].line == mine["u1"].line + 2


def test_where_an_item_was_declared_is_not_part_of_its_digest_or_its_reuse_key():
    """A lock accepted before the file was recorded still holds."""
    import dataclasses
    from placemat import lock, reuse
    b = _board()
    i = next(i for i in b._intents if i.key == "u1")
    moved = dataclasses.replace(i, file="/elsewhere/other.py", line=i.line + 40)
    assert lock.declaration_digest(b, i) == lock.declaration_digest(b, moved)
    assert reuse.canonical(i) == reuse.canonical(moved)
