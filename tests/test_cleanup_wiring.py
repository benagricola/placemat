"""The cleanup pass inside a resolve. Pure: synthetic boards."""
import dataclasses


import placemat.cleanup as cleanup_module
from placemat.layout import Board
from placemat.runner import run_metrics
from placemat.settings import Settings
from placemat.values import CopperLayer, Location, Near, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint


def _board(enabled=True):
    """r1 is pulled by j1 only when it goes down; r2, placed after it, is
    joined to r1 and to j2 across the board, so r1 does better moving once
    r2 is there."""
    fps = [footprint("J1", 5, 20, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("J2", 55, 20, w=2, h=2, inst="j2", nets=("C", "GND")),
           footprint("R1", 30, 30, w=4, h=2, inst="r1", nets=("A", "B")),
           footprint("R2", 32, 34, w=2, h=1, inst="r2", nets=("B", "C"))]
    b = Board(board_geometry(fps, width=60, height=40), edge_margin=0.5,
              settings=dataclasses.replace(Settings(), cleanup_enabled=enabled))
    b.place(Part("j1"), at=Location(5, 20))
    b.place(Part("j2"), at=Location(55, 20))
    return b


def _run(b, *parts):
    for p in parts:
        b.place(Part(p))
    return b.resolve()


def _wire(plan, g):
    total = 0.0
    for net in ("A", "B", "C"):
        pts = [plan.occupancy.pad_location(fp.ref, p.number) for fp in g.footprints for p in fp.pads if p.net == net]
        total += max(q.x for q in pts) - min(q.x for q in pts) + max(q.y for q in pts) - min(q.y for q in pts)
    return total


def test_a_part_placed_before_its_neighbours_moves_once_they_are_down():
    off = _board(False)
    before = _run(off, "r1", "r2")
    on = _board(True)
    after = _run(on, "r1", "r2")
    assert _wire(after, on.geometry) < _wire(before, off.geometry) - 1e-6
    assert any("cleanup:" in s.note for s in after.steps)
    assert after.cleanup["moves"] + after.cleanup["swaps"] >= 1
    assert after.cleanup["cost_after"] < after.cleanup["cost_before"]


def test_with_cleanup_off_placement_is_as_it_was(monkeypatch):
    def never(*a, **k):
        raise AssertionError("the pass ran with cleanup off")
    monkeypatch.setattr(cleanup_module, "cleanup", never)
    plan = _run(_board(False), "r1", "r2")
    assert plan.cleanup == {} and not any("cleanup" in s.note for s in plan.steps)


def test_a_part_the_script_positioned_or_labelled_or_referred_to_does_not_move():
    b = _board(True)
    b.place(Part("r1"), at=Near(Location(30, 30)))
    b.place(Part("r2"))
    plan = b.resolve()
    assert not any(s.item == "r1" and "cleanup" in s.note for s in plan.steps)
    b = _board(True)
    b.label(Part("r1"), "R1", side="N")
    b.place(Part("r1"))
    b.place(Part("r2"))
    plan = b.resolve()
    assert not any(s.item == "r1" and "cleanup" in s.note for s in plan.steps)
    b = _board(True)
    b.place(Part("r1"))
    b.place(Part("r2"), at=Near(PadRef(Part("r1"), 2), radius=4.0))
    plan = b.resolve()
    assert not any(s.item == "r1" and "cleanup" in s.note for s in plan.steps)


def test_fixed_parts_and_block_members_do_not_move():
    b = _board(True)
    blk = b.block(Part("r1"), satellites=[(Part("r2"), "B")], gap=0.5)
    b.place(blk)
    plan = b.resolve()
    assert not any("cleanup" in s.note for s in plan.steps)
    assert plan.placement("j1").location == Location(5, 20)


def test_the_run_records_what_the_pass_did():
    plan = _run(_board(True), "r1", "r2")
    m = run_metrics(plan, 4, 0, {})
    assert m["cleanup"]["moves"] == plan.cleanup["moves"]


def test_copper_planned_after_the_pass_reaches_the_pads_where_they_ended():
    b = _board(True)
    b.place(Part("r1"))
    b.place(Part("r2"))
    b.track(Net("B"), [PadRef(Part("r1"), 2), PadRef(Part("r2"), 1)], layer=CopperLayer.F)
    plan = b.resolve()
    end = plan.occupancy.pad_location("R2", "1")
    tracks = [op for op in plan.copper if getattr(op, "net", None) == "B"]
    assert tracks
    pts = [p for op in tracks for p in (op.start, op.end)]
    assert any(abs(p.x - end.x) < 1e-6 and abs(p.y - end.y) < 1e-6 for p in pts)
