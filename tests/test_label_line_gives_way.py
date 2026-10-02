"""A line of labels (a list, or `line=`) gives way as one: where a part placed
after it would stand on or within silk clearance of one of its texts, the whole
line slides along its side or changes side together, keeping its spacing and
order and staying next to its items; with no clear spot it stays and is a
finding. A part never moves for it. Pure: synthetic boards, and kicad-cli's DRC
on the written shapes."""
import dataclasses
import json
import subprocess

import pytest

from placemat.copper import Text
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Edge, Location, Near, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint

SILK = 0.2


def texts(plan):
    return sorted((op for op in plan.copper if isinstance(op, Text)), key=lambda t: t.text)


def make_board(room_south=True, walled=False, **kw):
    """SW1 and SW2 (x 3 and 7, y 9) labelled BOOT and RESET in a line above them,
    text running up the page; C1 is searched near the BOOT text and its pads
    land under it unless the line moves."""
    fps = [footprint("SW1", 3, 9, w=2, h=1, inst="sw1", nets=("A", "B")),
           footprint("SW2", 7, 9, w=2, h=1, inst="sw2", nets=("C", "D")),
           footprint("C1", 3, 5, w=2, h=1.5, inst="c1", nets=("E", "F"))]
    if walled:
        fps += [footprint("RW", 0.8, 9, w=1.6, h=1, inst="rw", nets=("G", "H")),
                footprint("RE", 9.2, 9, w=1.6, h=1, inst="re", nets=("I", "J"))]
    b = Board(board_geometry(fps, width=10, height=17 if room_south else 10.6, silk_clearance=SILK),
              edge_margin=0.5, settings=dataclasses.replace(Settings(), place_envelope="physical"), **kw)
    b.place(Part("sw1"), at=Location(3, 9))
    b.place(Part("sw2"), at=Location(7, 9))
    b.label([Part("sw1"), Part("sw2")], ["BOOT", "RESET"], side=Edge.NORTH, knockout=True, rotation=90)
    b.place(Part("c1"), at=Near(Location(3, 5), radius=1.0), rotations=(0.0,))
    return b


def test_the_line_moves_as_one_for_a_part_searched_after_it():
    first = make_board()
    plan = first.resolve()
    assert plan.placement("c1") is not None
    boot, reset = texts(plan)
    assert not [f for f in plan.findings if f.kind in ("unplaced", "label")], list(plan.findings)
    pads = [s for s in plan.occupancy.items["C1"].shapes if s.kind == "pad"]
    for t in (boot, reset):
        assert not any(t.box.overlaps(p.box) for p in pads)
    assert boot.side is reset.side
    # the spacing along the line is the declared one (4 mm between the two items)
    along = (lambda t: t.at.x) if boot.side in (Edge.NORTH, Edge.SOUTH) else (lambda t: t.at.y)
    assert along(reset) - along(boot) == pytest.approx(4.0 if boot.side in (Edge.NORTH, Edge.SOUTH) else 0.0)
    assert "moved from" in plan.step("label sw1 BOOT").note and "moved from" in plan.step("label sw2 RESET").note
    assert plan.placement("sw1").location == Location(3, 9) and plan.placement("sw2").location == Location(7, 9)


def test_a_line_with_no_clear_spot_stays_and_is_a_finding_and_the_part_places():
    plan = make_board(room_south=False, walled=True, keep_going=True).resolve()
    assert plan.placement("c1") is not None
    boot, reset = texts(plan)
    assert boot.side is Edge.NORTH and reset.side is Edge.NORTH
    said = [str(f) for f in plan.findings if f.kind == "label" and "no clear spot" in str(f)]
    assert said, list(plan.findings)


def test_a_replayed_run_ends_with_the_line_where_the_fresh_run_put_it():
    first = make_board().resolve()
    again = make_board().resolve(reuse=first.reuse)
    assert again.reuse["reused"] > 0
    assert texts(again) == texts(first)
    assert again.placements == first.placements
    assert again.findings == first.findings


@needs_kicad
def test_kicad_finds_no_silk_over_copper_once_the_line_has_moved(tmp_path):
    import pcbnew
    from placemat.kicad.write import _draw_text, vec
    plan = make_board().resolve()
    board = pcbnew.CreateEmptyBoard()
    n = 0
    for ref, g in plan.occupancy.items.items():
        kfp = pcbnew.FOOTPRINT(board)
        kfp.SetReference(ref)
        for s in g.shapes:
            if s.kind != "pad":
                continue
            n += 1
            kp = pcbnew.PAD(kfp)
            kp.SetShape(pcbnew.PAD_SHAPE_RECT)
            kp.SetSize(vec(s.box.width, s.box.height))
            kp.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            ls = pcbnew.LSET()
            ls.AddLayer(pcbnew.F_Cu)
            ls.AddLayer(pcbnew.F_Mask)
            kp.SetLayerSet(ls)
            kp.SetPosition(vec(s.box.center.x, s.box.center.y))
            kp.SetNumber(str(n))
            kfp.Add(kp)
        board.Add(kfp)
    for op in plan.copper:
        if isinstance(op, Text):
            _draw_text(board, op)
    pcb = tmp_path / "line.kicad_pcb"
    board.Save(str(pcb))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    found = [v for v in json.loads(report.read_text()).get("violations", []) if v.get("type") == "silk_over_copper"]
    assert found == []


def test_pad_labels_standing_off_their_part_move_as_one_too():
    from placemat.values import PadRef
    fps = [footprint("J1", 5, 9, w=6, h=1, inst="j1", nets=("A", "B")),
           footprint("C1", 2.6, 5, w=2, h=1.5, inst="c1", nets=("E", "F"))]
    b = Board(board_geometry(fps, width=10, height=17, silk_clearance=SILK), edge_margin=0.5,
              settings=dataclasses.replace(Settings(), place_envelope="physical"))
    b.place(Part("j1"), at=Location(5, 9))
    b.label([PadRef(Part("j1"), 1), PadRef(Part("j1"), 2)], ["GND", "CLK"], side=Edge.NORTH, rotation=90,
            line=Part("j1"))
    b.place(Part("c1"), at=Near(Location(2.6, 5), radius=1.0), rotations=(0.0,))
    plan = b.resolve()
    gnd, clk = texts(plan)[::-1] if texts(plan)[0].text == "GND" else texts(plan)
    assert plan.placement("c1").location == Location(2.6, 5.0)
    pads = [s for s in plan.occupancy.items["C1"].shapes if s.kind == "pad"]
    assert not any(t.box.overlaps(p.box) for t in (gnd, clk) for p in pads)
    assert gnd.side is clk.side and gnd.side is not Edge.NORTH
    assert not [f for f in plan.findings if f.kind in ("unplaced", "label")], list(plan.findings)
