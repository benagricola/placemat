"""An unlinked part no free rectangle of the pocket raster takes is still scanned for over the whole face. Pure."""
from placemat.layout import Board
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


def _l_room(part_h=5.6):
    """A 40 x 30 board whose free room is an L: a corridor 5.7 wide down x 17.15..22.85, and an arm along the top
    east of it, 5.6 high. Both are off the pocket raster's 0.5 mm cells, which round each side out by a cell, so no
    rectangle the raster calls free holds a 5.6 x `part_h` part; the part fits the corridor exactly with clearance."""
    walls = [("W1", 8.575, 15.0, 17.15, 30.0), ("W2", 31.425, 12.2, 17.15, 24.4)]
    fps = [footprint(r, cx, cy, w=w, h=h, inst=r.lower(), nets=("X" + r, "Y" + r), excess=0.0) for r, cx, cy, w, h in walls]
    fps.append(footprint("U1", 5.0, 5.0, w=5.6, h=part_h, inst="u1", nets=("U1A", "U1B"), excess=0.0))
    b = Board(board_geometry(fps, width=40, height=30), edge_margin=0.0, keep_going=True)
    for r, cx, cy, _, _ in walls:
        b.place(Part(r.lower()), at=Location(cx, cy))
    return b


def test_a_part_the_pocket_raster_cannot_see_room_for_is_found_by_a_scan_of_the_face():
    b = _l_room()
    b.place(Part("u1"), rotations=(0.0,))
    plan = b.resolve()
    step = plan.step("u1")
    assert step.placement is not None, step.note
    box = plan.box("u1")
    assert box.left >= 17.15 - 1e-6 and box.right <= 22.85 + 1e-6, box          # in the corridor, clear of both walls
    assert "scan" in step.note
    assert not [f for f in plan.findings if f.startswith("u1")]


def test_a_part_that_fits_nowhere_is_still_unplaced_and_the_finding_says_the_scan_failed_too():
    fps = [footprint("W1", 8.575, 15.0, w=17.15, h=30.0, inst="w1", nets=("XW1", "YW1"), excess=0.0),
           footprint("W2", 31.425, 12.2, w=17.15, h=24.4, inst="w2", nets=("XW2", "YW2"), excess=0.0),
           footprint("U1", 5.0, 5.0, w=5.8, h=5.8, inst="u1", nets=("U1A", "U1B"), excess=0.0)]
    b = Board(board_geometry(fps, width=40, height=30), edge_margin=0.0, keep_going=True)
    b.place(Part("w1"), at=Location(8.575, 15.0))
    b.place(Part("w2"), at=Location(31.425, 12.2))
    b.place(Part("u1"), rotations=(0.0,))
    plan = b.resolve()
    assert plan.step("u1").placement is None
    assert any(f.startswith("u1:") and "no pocket fits" in f and "scan" in f for f in plan.findings), plan.findings
