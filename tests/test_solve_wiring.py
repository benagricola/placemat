"""The global solve inside a resolve. Pure: synthetic boards."""
import dataclasses

from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Location, Near, Part
from tests.fixtures import board_geometry, footprint


def _board(enabled):
    fps = [footprint("J1", 5, 20, w=2, h=2, inst="j1", nets=("A", "GND")),
           footprint("U1", 30, 30, w=4, h=2, inst="u1", nets=("A", "B")),
           footprint("R1", 32, 34, w=2, h=1, inst="r1", nets=("B", "C")),
           footprint("J2", 45, 20, w=2, h=2, inst="j2", nets=("C", "GND"))]
    b = Board(board_geometry(fps, width=50, height=40), edge_margin=0.5,
              settings=dataclasses.replace(Settings(), solve_enabled=enabled))
    b.place(Part("j1"), at=Location(5, 20))
    b.place(Part("j2"), at=Location(45, 20))
    return b


def test_with_the_solve_on_the_first_searched_item_is_seeded_from_the_netlist():
    b = _board(True)
    b.place(Part("u1"))
    b.place(Part("r1"))
    plan = b.resolve()
    notes = {s.item: s.note for s in plan.steps}
    assert "global solve" in notes["u1"] and "global solve" in notes["r1"]
    assert "nothing it connects to is placed" not in notes["u1"]


def test_an_explicit_near_beats_the_solve():
    b = _board(True)
    b.place(Part("u1"), at=Near(Location(25, 10)))
    b.place(Part("r1"))
    plan = b.resolve()
    assert "global solve" not in {s.item: s.note for s in plan.steps}["u1"]


def test_with_the_solve_off_placement_is_as_it_was():
    def run():
        b = _board(False)
        b.place(Part("u1"))
        b.place(Part("r1"))
        return [(s.item, s.placement) for s in b.resolve().steps]
    assert run() == run()
    b = _board(False)
    b.place(Part("u1"))
    b.place(Part("r1"))
    assert all("global solve" not in s.note for s in b.resolve().steps)


def test_an_item_with_nothing_that_pulls_still_takes_a_pocket():
    fps = [footprint("J1", 5, 20, inst="j1", nets=("A", "GND")),
           footprint("X1", 30, 30, inst="x1", nets=("P", "Q"))]
    b = Board(board_geometry(fps, width=50, height=40), edge_margin=0.5,
              settings=dataclasses.replace(Settings(), solve_enabled=True))
    b.place(Part("j1"), at=Location(5, 20))
    b.place(Part("x1"))
    note = {s.item: s.note for s in b.resolve().steps}["x1"]
    assert "pocket" in note and "global solve" not in note


def test_the_plan_records_what_the_solve_did():
    b = _board(True)
    b.place(Part("u1"))
    b.place(Part("r1"))
    plan = b.resolve()
    assert plan.solve["seeded"] == 2 and plan.solve["rounds"] >= 1


def test_a_block_keeps_its_own_seeding_when_the_solve_is_on():
    """A block's item is its spec, not a part: on a real board the solve
    crashed reading a refdes off it. Blocks keep the path they have."""
    fps = [footprint("U9", 150, 60, w=4, h=2, inst="ldo", nets=("VIN", "VOUT")),
           footprint("C8", 160, 60, w=2, h=1, inst="cin", nets=("VIN", "GND")),
           footprint("R5", 140, 60, w=2, h=1, inst="r5", nets=("VOUT", "FB")),
           footprint("J1", 5, 5, w=4, h=2, inst="j1", nets=("VIN", "GND"))]
    b = Board(board_geometry(fps, width=50, height=50), edge_margin=1.0,
              settings=dataclasses.replace(Settings(), solve_enabled=True))
    b.place(Part("j1"), at=Location(40, 40))
    b.place(b.block(Part("ldo"), satellites=[(Part("cin"), "VIN")]), radius=4.0)
    b.place(Part("r5"))
    plan = b.resolve()
    notes = {s.item: s.note for s in plan.steps}
    assert "global solve" in notes["r5"]
    assert not any("global solve" in n for k, n in notes.items() if "ldo" in k)


def test_a_solved_hint_that_cannot_be_legalised_falls_back_to_the_seed(monkeypatch):
    """On a real board the solve put two small parts against the edge beside a
    connector, the scan found nothing there, and they went unplaced where the
    sequential seed would have placed them. A hint that fails is dropped for
    the path the item had without the solve."""
    b = _board(True)
    b.place(Part("u1"))
    b.place(Part("r1"))
    monkeypatch.setattr(Board, "_global_hints",
                        lambda self, occ, placed, plan: {"u1": Location(-100.0, -100.0), "r1": Location(-100.0, -100.0)})   # nothing legal within reach
    plan = b.resolve()
    steps = {s.item: s for s in plan.steps}
    assert steps["u1"].placement is not None and steps["r1"].placement is not None
    assert "solve's hint" in steps["u1"].note


def test_the_docs_describe_the_solve_and_its_default():
    from pathlib import Path
    api = " ".join(Path("skills/placemat/references/api.md").read_text().split())
    assert "[solve] enabled = true" in api and "off by default" in api.lower()
    assert "quarter of the free board" not in api                      # the rule the rank replaced
    assert "## To 0.20" in Path("skills/placemat/references/migration.md").read_text()
