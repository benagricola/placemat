"""Seeding a cell: its own nets first, a pocket that fits second, a hint last.

A coordinate says where there was room when somebody looked, and nothing about
where a cell's nets are. These are the two searches that answer it instead, on
a real cell fragment.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pcbnew                                                # noqa: E402
from placemat.layout_helpers import ModuleLayout                      # noqa: E402
from placemat.board_layout import BoardLayout                         # noqa: E402

CELL = os.path.join(ROOT, "tests", "fixtures", "ProtectionCell", "layout", "layout.kicad_pcb")


@pytest.fixture
def bl(tmp_path):
    import shutil
    work = tmp_path / "b.kicad_pcb"
    shutil.copy(CELL, work)
    layout = ModuleLayout(str(work))
    return BoardLayout(layout, width=60.0, height=60.0, plane_nets={"gnd"})



@pytest.mark.board
def test_a_cell_with_nothing_placed_has_no_net_seed(bl):
    """Nothing to aim at: the answer is None, not a coordinate invented to fill
    the gap. That is what sends settle_cell to the pocket scan."""
    name = sorted(bl.cells)[0] if bl.cells else None
    if name is None:
        pytest.skip("fragment carries no group to treat as a cell")
    assert bl.cell_seed(name) is None
