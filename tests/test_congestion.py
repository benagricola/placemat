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


def test_a_large_pad_is_not_a_congested_cell():
    """Pads do not take capacity: a cell under a large pad would otherwise
    have none, and read as the worst on the board whatever the wiring."""
    wire = [_pad("A", 1.0, 1.0, s=0.1), _pad("A", 9.0, 1.0, s=0.1)]
    alone = rudy(wire, Box(0, 0, 10, 10), layers=2, pitch=0.4, cell=1.0)
    padded = rudy(wire + [_pad("GND", 5.0, 5.0, s=3.0), _pad("GND", 5.5, 5.5, s=0.1)], Box(0, 0, 10, 10), layers=2,
                  pitch=0.4, cell=1.0, skip={"GND"})
    assert padded.worst == alone.worst and padded.worst < 1.0


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


def test_grid_signed_changes_match_rebuilt_grid_and_leave_baseline_unchanged():
    import random
    from placemat.congestion import RudyGrid
    from placemat.values import Location
    rng = random.Random(4)
    box = Box(0, 0, 20, 20)
    points = {str(i): [Location(rng.uniform(0, 20), rng.uniform(0, 20)) for _ in range(4)] for i in range(6)}
    grid = RudyGrid(box, 2, 0.4, 0.05)
    for net, pads in points.items():
        grid.add_net(net, pads)
    baseline = grid.steps()
    saved = list(grid.demand)
    for _ in range(100):
        replacements = {net: [Location(rng.uniform(0, 20), rng.uniform(0, 20)) for _ in range(4)]
                        for net in rng.sample(list(points), 2)}
        rebuilt = RudyGrid(box, 2, 0.4, 0.05)
        for net, pads in dict(points, **replacements).items():
            rebuilt.add_net(net, pads)
        assert grid.change(replacements) == rebuilt.steps() - baseline
        assert grid.demand == saved and grid.steps() == baseline


def test_spreading_a_net_can_lower_congestion():
    from placemat.congestion import RudyGrid
    from placemat.values import Location
    grid = RudyGrid(Box(0, 0, 20, 20), 2, 0.4, 0.05)
    grid.add_net('n', [Location(1, 1), Location(1.1, 1.1)])
    assert grid.change({'n': [Location(1, 1), Location(15, 15)]}) < 0


def test_grid_repeated_net_changes_do_not_drift_at_step_boundaries():
    from placemat.congestion import RudyGrid
    from placemat.values import Location
    grid = RudyGrid(Box(0, 0, 10, 10), 2, 0.4, 0.05)
    baseline = [Location(1, 1), Location(1.000000001, 1.000000001)]
    grid.add_net('a', baseline)
    grid.add_net('b', baseline)
    before = list(grid.demand), grid.steps()
    for _ in range(1000):
        grid.remove_net('a')
        grid.add_net('a', [Location(1, 1), Location(8, 8)])
        grid.add_net('a', baseline)
    assert (grid.demand, grid.steps()) == before


def test_grid_worst_matches_display_rudy_and_removing_all_pads_clears_it():
    from placemat.congestion import RudyGrid
    from placemat.values import Location
    box = Box(0, 0, 10, 10)
    grid = RudyGrid(box, 2, 0.4, 0.05)
    points = [Location(1.2, 2.3), Location(6.7, 8.9)]
    grid.add_net('a', points)
    display = rudy([_pad('a', p.x, p.y) for p in points], box, 2, 0.4)
    assert grid.worst() == pytest.approx(display.worst, abs=0.00005)
    assert grid.change({'a': []}) == -grid.steps()
    grid.remove_net('a')
    assert grid.steps() == 0 and grid.worst() == 0


def test_a_net_box_is_floored_at_the_set_width_about_its_centre():
    """`score.congestion_box`: a net along one axis spreads its wire over the floor's width, not one cell."""
    pads = [_pad("A", 2.0, 5.25), _pad("A", 4.0, 5.25)]
    thin = rudy(pads, Box(0, 0, 10, 10), layers=2, pitch=0.4, cell=0.5)
    wide = rudy(pads, Box(0, 0, 10, 10), layers=2, pitch=0.4, cell=0.5, box=2.0)
    assert wide.demand == thin.demand == pytest.approx(2.0)
    assert wide.worst == pytest.approx(thin.worst / 4, abs=1e-4)          # 2 mm high, not 0.5 mm
    assert wide.worst_at.y == pytest.approx(thin.worst_at.y, abs=1.0)
    assert rudy(pads, Box(0, 0, 10, 10), 2, 0.4, cell=0.5, box=0.5).worst == thin.worst


def test_grid_changes_across_the_box_floor_match_a_rebuilt_grid_and_the_display():
    import random
    from placemat.congestion import RudyGrid
    from placemat.values import Location
    rng = random.Random(7)
    box = Box(0, 0, 12, 12)
    rest = {str(i): [Location(rng.uniform(1, 11), rng.uniform(1, 11)) for _ in range(3)] for i in range(5)}
    grid = RudyGrid(box, 2, 0.4, 0.05, box=2.5)
    for net, pads in rest.items():
        grid.add_net(net, pads)
    grid.add_net("s", [Location(5, 5), Location(6, 5)])
    baseline = grid.steps()
    widths = set()
    for _ in range(200):
        x, y = rng.uniform(4, 9), rng.uniform(4, 6)                     # the short net's box crosses 2.5 mm either way
        moved = [Location(5, 5), Location(x, y)]
        widths.add((abs(x - 5) < 2.5, abs(y - 5) < 2.5))
        rebuilt = RudyGrid(box, 2, 0.4, 0.05, box=2.5)
        for net, pads in dict(rest, s=moved).items():
            rebuilt.add_net(net, pads)
        assert grid.change({"s": moved}) == rebuilt.steps() - baseline
        display = rudy([_pad(net, p.x, p.y) for net, pads in dict(rest, s=moved).items() for p in pads],
                       box, 2, 0.4, box=2.5)
        assert rebuilt.worst() == pytest.approx(display.worst, abs=0.00005)
    assert {w for w, _ in widths} == {True, False}


def test_the_native_cells_keep_the_python_grids_sums_bit_for_bit():
    """RudyGrid's cells kept natively (rudy.rs) give the demand, steps, worst and candidate changes the Python cells
    give, bit for bit, through adds, moves, removals and change questions in any order."""
    import random
    from placemat import congestion
    from placemat.values import Box, Location
    if congestion._native_cells() is None:
        pytest.skip("native module not built")
    rng = random.Random(3)
    board = Box(0.0, 0.0, 30.0, 20.0)
    native = congestion.RudyGrid(board, 2, 0.4, 0.5, box=1.0)
    plain = congestion.RudyGrid(board, 2, 0.4, 0.5, box=1.0)
    plain._native, plain.cells = None, [{} for _ in plain._demand]

    def points():
        return [Location(rng.uniform(-2, 32), rng.uniform(-2, 22)) for _ in range(rng.choice([1, 2, 3, 5]))]
    nets = ["N%d" % i for i in range(12)]
    for _ in range(400):
        net = rng.choice(nets)
        roll = rng.random()
        if roll < 0.55:
            p = points()
            native.add_net(net, p)
            plain.add_net(net, p)
        elif roll < 0.7:
            native.remove_net(net)
            plain.remove_net(net)
        else:
            ask = {rng.choice(nets): points() for _ in range(rng.choice([1, 2, 3]))}
            assert native.change(ask) == plain.change(ask)
        assert native.demand == plain.demand
        assert native.steps() == plain.steps() and native.worst() == plain.worst()
