from placemat.occupancy import Occupancy
from placemat.placer import edge_placement, scan
from placemat.placement import Placement
from placemat.values import Box, Edge, Face, Location
from tests.fixtures import board_geometry, footprint


def test_scan_returns_the_hint_when_it_is_legal():
    occ = Occupancy(board_geometry([footprint("R1", 10, 10)]), edge_margin=1.0)
    r2 = footprint("R2", 30, 30)
    result = scan(occ, r2, hint=Placement(Location(30, 30), 0, Face.FRONT), radius=3.0, step=0.5)
    assert result.chosen.location == Location(30, 30)
    assert result.tried >= 1 and not result.rejected


def test_scan_moves_off_an_obstacle_to_the_nearest_legal_location():
    occ = Occupancy(board_geometry([footprint("R1", 10, 10)]), edge_margin=1.0)
    r2 = footprint("R2", 30, 30)
    result = scan(occ, r2, hint=Placement(Location(10, 10), 0, Face.FRONT), radius=6.0, step=0.5)
    chosen = result.chosen
    assert chosen is not None
    assert occ.legal(r2, chosen) is None
    # nothing legal closer to the hint was skipped
    assert result.moved_mm > 0
    assert "courtyard" in " ".join(result.rejected)


def test_scan_is_deterministic_and_prefers_the_smaller_rotation_on_ties():
    occ = Occupancy(board_geometry([footprint("R1", 10, 10)]), edge_margin=1.0)
    r2 = footprint("R2", 30, 30, w=2, h=2)
    a = scan(occ, r2, hint=Placement(Location(30, 30), 0, Face.FRONT), radius=2.0, step=0.5,
             rotations=(0, 90, 180, 270))
    b = scan(occ, r2, hint=Placement(Location(30, 30), 0, Face.FRONT), radius=2.0, step=0.5,
             rotations=(270, 180, 90, 0))
    assert a.chosen == b.chosen and a.chosen.rotation == 0


def test_scan_reports_failure_with_reasons_when_nothing_fits():
    occ = Occupancy(board_geometry([footprint("R1", 10, 10, w=20, h=20)]), edge_margin=1.0)
    r2 = footprint("R2", 30, 30)
    result = scan(occ, r2, hint=Placement(Location(10, 10), 0, Face.FRONT), radius=2.0, step=1.0)
    assert result.chosen is None
    assert result.rejected and result.tried > 0


def test_edge_placement_puts_the_body_box_at_the_margin():
    occ = Occupancy(board_geometry([], width=100, height=60), edge_margin=1.0)
    r = footprint("J1", 50, 30, w=10, h=4)
    p = edge_placement(occ, r, Edge.NORTH, along=40.0, rotation=0, clearance=3.0)
    box = occ.body_box(r, p)
    assert abs(box.top - 3.0) < 1e-9 and abs(box.center.x - 40.0) < 1e-9
    p = edge_placement(occ, r, Edge.EAST, along=20.0, rotation=90, clearance=3.0)
    box = occ.body_box(r, p)
    assert abs(box.right - 97.0) < 1e-9 and abs(box.center.y - 20.0) < 1e-9
    assert abs(box.width - 4.0) < 1e-9        # rotated: the 10 mm side runs along the edge


def test_edge_placement_of_a_cell_moves_every_member():
    fps = [footprint("U1", 10, 10, w=6, h=2, cell="pd", inst="pd.conn"),
           footprint("F1", 10, 14, w=6, h=2, cell="pd", inst="pd.fuse")]
    occ = Occupancy(board_geometry(fps, cells=["pd"], width=100, height=100), edge_margin=1.0)
    cell = occ.geometry.cell("pd")
    p = edge_placement(occ, cell, Edge.WEST, along=50.0, rotation=0, clearance=2.0)
    box = occ.body_box(cell, p)
    assert abs(box.left - 2.0) < 1e-9 and abs(box.center.y - 50.0) < 1e-9
    assert abs(box.height - 6.0) < 1e-9


def test_a_scored_scan_over_a_wide_radius_is_coarse_then_fine_and_tries_far_fewer_candidates():
    """With a score every legal candidate is weighed, so a wide radius at a
    fine step is thousands of checks. The scan runs coarse first (four
    steps) and refines to the fine step only around the best coarse spots;
    it still lands on a fine-grid point with the lowest score."""
    occ = Occupancy(board_geometry([footprint("R1", 10, 10)], width=80, height=80), edge_margin=1.0)
    r2 = footprint("R2", 30, 30)
    target = Location(41.3, 33.1)
    score = lambda p: p.location.distance(target)
    wide = scan(occ, r2, hint=Placement(Location(30, 30), 0, Face.FRONT), radius=16.0, step=0.2, score=score)
    assert wide.chosen is not None and wide.chosen.location.distance(target) < 0.15      # on the fine grid, next to the target
    full_grid = sum(1 for _ in range(int(16 / 0.2) * 2 + 1)) ** 2
    assert wide.tried < full_grid / 8


def test_a_scored_scan_still_finds_a_spot_that_only_the_fine_grid_reaches():
    # a 2.2 wide slot between two blocks: the coarse 0.8 grid may straddle it, the fine pass must not miss it
    fps = [footprint("A1", 20, 20, w=10, h=10), footprint("A2", 32.2, 20, w=10, h=10)]
    occ = Occupancy(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    r = footprint("R2", 50, 50, w=1.6, h=1.0)
    score = lambda p: p.location.distance(Location(26.1, 20))
    result = scan(occ, r, hint=Placement(Location(26.3, 20), 0, Face.FRONT), radius=2.0, step=0.2, score=score)
    assert result.chosen is not None and abs(result.chosen.location.x - 26.1) < 0.25
