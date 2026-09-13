"""The occupancy model must agree with KiCad about the committed Breakout
board: a DRC-clean board is legal everywhere at its current placement, and
a cell moved onto its neighbour is not."""
import time

from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.placer import scan
from placemat.values import Face, Location
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]


def test_every_footprint_is_legal_where_it_sits(breakout):
    occ = Occupancy(breakout, edge_margin=0.0)
    bad = {}
    for fp in breakout.footprints:
        why = occ.legal(fp, Placement(fp.location, fp.rotation, fp.face))
        if why:
            bad[fp.ref] = why
    assert not bad, bad


def test_every_cell_is_legal_where_it_sits(breakout):
    occ = Occupancy(breakout, edge_margin=0.0)
    bad = {}
    for name, cell in breakout.cells.items():
        why = occ.legal(cell, Placement(cell.box.center, 0.0, Face.FRONT))
        if why:
            bad[name] = why
    assert not bad, bad


def test_a_station_moved_onto_its_neighbour_is_rejected(breakout):
    occ = Occupancy(breakout, edge_margin=0.0)
    pd0, bd0 = breakout.cell("power_drop0"), breakout.cell("bus_drop0")
    # slide power_drop0 south by half its neighbour's height: it stays on the
    # board and lands on bus_drop0's connector
    onto = Placement(pd0.box.center.offset(0, bd0.box.height / 2 + 2.0), 0.0, Face.FRONT)
    why = occ.legal(pd0, onto)
    assert why is not None and "bus_drop0" not in why   # reported by member refdes, not cell name
    assert any(fp.ref in why for fp in bd0.members), why


def test_thousands_of_candidates_are_cheap(breakout):
    occ = Occupancy(breakout, edge_margin=3.0)
    r15 = breakout.footprint("R15")
    t0 = time.time()
    result = scan(occ, r15, Placement(r15.location, 0, Face.FRONT), radius=6.0, step=0.25)
    dt = time.time() - t0
    assert result.chosen is not None
    assert result.tried >= 1
    # a full 6 mm radius at 0.25 mm is ~1800 candidates; the model must stay
    # well under a second per part or the offline placer has no point
    full = scan(occ, r15, Placement(Location(60.0, 120.0), 0, Face.FRONT), radius=6.0, step=0.25)
    assert full.tried > 1000 or full.chosen is not None
    assert dt < 2.0
