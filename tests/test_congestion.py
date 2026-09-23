"""RUDY: each net's wire spread evenly over its box, against what a cell of
the board can carry. The worst cell is reported with every run."""
import pytest

from placemat.congestion import rudy
from placemat.values import Box


def _pad(net, x, y, s=0.4, layers=1):
    return (net, Box(x - s / 2, y - s / 2, x + s / 2, y + s / 2), layers)


def test_one_net_spreads_its_wire_evenly_over_its_box():
    r = rudy([_pad("A", 1.0, 1.0), _pad("A", 9.0, 5.0)], Box(0, 0, 10, 6), layers=2, pitch=0.4, cell=1.0)
    assert r.demand == pytest.approx(12.0)                     # 8 + 4 mm of wire
    assert r.cells > 0


def test_the_worst_cell_is_where_nets_crowd():
    pads = [_pad("N%d" % k, 1.0, 1.0 + k * 0.1) for k in range(6)] + [_pad("N%d" % k, 3.0, 1.0 + k * 0.1) for k in range(6)]
    pads += [_pad("Z", 15.0, 15.0), _pad("Z", 18.0, 15.0)]
    r = rudy(pads, Box(0, 0, 20, 20), layers=2, pitch=0.4, cell=1.0)
    assert r.worst_at.x < 5 and r.worst_at.y < 3
    assert r.worst > r.p99 >= 0


def test_pads_take_capacity_from_the_cells_they_cover():
    open_board = rudy([_pad("A", 1.0, 1.0, s=0.1), _pad("A", 4.0, 1.0, s=0.1)], Box(0, 0, 10, 10), layers=1, pitch=0.4, cell=1.0)
    blocked = rudy([_pad("A", 1.0, 1.0, s=0.1), _pad("A", 4.0, 1.0, s=0.1), _pad("B", 2.5, 1.0, s=0.9), _pad("C", 2.5, 3.0, s=0.9)],
                   Box(0, 0, 10, 10), layers=1, pitch=0.4, cell=1.0)
    assert blocked.worst > open_board.worst


def test_single_pin_nets_and_nets_left_out_ask_for_nothing():
    r = rudy([_pad("A", 1.0, 1.0), _pad("GND", 1.0, 1.0), _pad("GND", 9.0, 9.0)], Box(0, 0, 10, 10), layers=2,
             pitch=0.4, cell=1.0, skip={"GND"})
    assert r.demand == 0.0 and r.worst == 0.0


def test_a_resolve_reports_its_worst_cell_and_the_run_records_it():
    from placemat.layout import Board
    from placemat.runner import run_metrics
    from placemat.values import Location, Part
    from tests.fixtures import board_geometry, footprint
    fps = [footprint("J1", 5, 10, inst="j1", nets=("A", "GND")),
           footprint("R1", 20, 10, inst="r1", nets=("A", "B")),
           footprint("R2", 30, 12, inst="r2", nets=("B", "GND")),
           footprint("X9", 90, 90, inst="x9", nets=("A", "B"))]              # never placed: asks for nothing
    b = Board(board_geometry(fps, width=40, height=20), edge_margin=0.5)
    b.place(Part("j1"), at=Location(5, 10))
    b.place(Part("r1"), at=Location(20, 10))
    b.place(Part("r2"), at=Location(30, 12))
    plan = b.resolve()
    r = plan.rudy
    assert r.worst > 0 and 0 <= r.worst_at.x <= 40 and 0 <= r.worst_at.y <= 20
    m = run_metrics(plan, 3, 0, {})
    assert m["rudy"]["worst"] == r.worst and m["rudy"]["worst_at"] == [r.worst_at.x, r.worst_at.y]


def test_the_grid_is_kept_and_its_worst_cell_is_the_worst():
    pads = [_pad("N%d" % k, 1.0, 1.0 + k * 0.1) for k in range(6)] + [_pad("N%d" % k, 3.0, 1.0 + k * 0.1) for k in range(6)]
    r = rudy(pads, Box(0, 0, 20, 10), layers=2, pitch=0.4, cell=1.0)
    assert len(r.util) == 10 and len(r.util[0]) == 20
    assert (r.origin.x, r.origin.y) == (0, 0)
    i, j = int((r.worst_at.x - r.origin.x) // r.cell), int((r.worst_at.y - r.origin.y) // r.cell)
    assert r.util[j][i] == pytest.approx(r.worst, abs=1e-4)
