"""Explore's focus: which searched items may vary. Each declaration knows
the script line it came from, so "everything after line N" can be said."""
import inspect

import pytest

from placemat.explore import focus_keys
from placemat.layout import Board
from placemat.values import Box, Cell, Edge, Location, OnEdge, Part
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("U1", 10, 10, w=6, h=3, inst="mcu", nets=("A", "B")),
           footprint("R1", 60, 60, w=2, h=1, inst="r1", nets=("A", "X")),
           footprint("R2", 60, 65, w=2, h=1, inst="r2", nets=("B", "Y")),
           footprint("J1", 60, 70, w=4, h=2, inst="j1", nets=("X", "Y")),
           footprint("U2", 40, 40, w=4, h=2, cell="pwr", inst="pwr.u", nets=("A", "Z"))]
    return Board(board_geometry(fps, cells=["pwr"], width=60, height=60), edge_margin=1.0)


def test_a_declaration_records_the_script_line_it_came_from():
    b = _board()
    line = inspect.currentframe().f_lineno + 1
    intent = b.place(Part("r1"))
    assert intent.line == line


def _declared():
    b = _board()
    b.place(Part("mcu"), at=Location(20, 20))          # fixed: never in focus
    b.place(Part("j1"), at=OnEdge(Edge.NORTH))          # an edge slot: never in focus
    b.place(Cell("pwr"))
    split = b.place(Part("r1")).line
    b.place(Part("r2"))
    return b, split


def test_with_no_focus_every_searched_item_is_in_focus():
    b, _ = _declared()
    assert focus_keys(b) == {"pwr", "r1", "r2"}


def test_focus_by_key_names_items_and_a_cell_counts_as_itself():
    b, _ = _declared()
    assert focus_keys(b, keys=["r2", "pwr"]) == {"r2", "pwr"}
    with pytest.raises(KeyError, match="no searched item"):
        focus_keys(b, keys=["mcu"])                    # fixed: nothing to vary


def test_focus_after_a_line_takes_what_was_declared_from_it_on():
    b, split = _declared()
    assert focus_keys(b, after_line=split) == {"r1", "r2"}


def test_focus_in_a_box_takes_what_the_plain_run_put_there():
    b, _ = _declared()
    plan = b.resolve()
    r1 = plan.box("r1")
    box = Box(r1.left - 0.01, r1.top - 0.01, r1.right + 0.01, r1.bottom + 0.01)
    assert focus_keys(b, box=box, baseline=plan) == {"r1"}


def test_a_declaration_s_line_is_not_in_its_reuse_key():
    """A comment added above a declaration moves its line; nothing it
    decides has changed, so it must still replay."""
    import dataclasses
    from placemat import reuse
    b = _board()
    i = b.place(Part("r1"))
    moved = dataclasses.replace(i, line=i.line + 40)
    assert reuse.step_key("k", i, []) == reuse.step_key("k", moved, [])
