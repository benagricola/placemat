"""Fixtures for placemat's own tests - no board repo required.

The cell under `tests/fixtures/` is a real module fragment, checked in, because
a synthetic footprint does not have the pads, courtyards and clearances the
library actually meets. It is the whole reason these tests can run in a
checkout with nothing else around it.
"""
import os
import shutil

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
CELL = os.path.join(HERE, "fixtures", "ProtectionCell", "layout", "layout.kicad_pcb")


@pytest.fixture
def cell_path(tmp_path):
    """A writable copy of the fixture cell."""
    dst = tmp_path / "layout.kicad_pcb"
    shutil.copy(CELL, dst)
    return str(dst)


@pytest.fixture(autouse=True)
def isolated_project():
    """Every test starts with no active project, so none of them leak one."""
    from placemat import project
    project.clear()
    yield
    project.clear()


# -- unit-level fixtures ------------------------------------------------------

@pytest.fixture
def bare():
    """A ModuleLayout over an EMPTY in-memory board: no file, no netlist.

    Enough to exercise every drawer and every geometry predicate, which is the
    point - a primitive that needs a 263-part board to test is a primitive
    nobody tests."""
    import pcbnew
    from placemat.layout_helpers import ModuleLayout
    layout = ModuleLayout.__new__(ModuleLayout)
    layout.pcb = pcbnew.BOARD()
    layout.path = None
    layout.footprints = {}
    layout.netcode = {}
    layout.links = []
    layout.on_save = []
    layout.before_save = []
    net = pcbnew.NETINFO_ITEM(layout.pcb, "T")
    layout.pcb.Add(net)
    layout.netcode["T"] = net.GetNetCode()
    return layout


def segments(layout):
    """Every track on the board as (x0, y0, x1, y1) in mm."""
    import pcbnew
    from placemat.layout_helpers import to_mm
    out = []
    for t in layout.pcb.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T:
            continue
        s, e = t.GetStart(), t.GetEnd()
        out.append((to_mm(s.x), to_mm(s.y), to_mm(e.x), to_mm(e.y)))
    return out
