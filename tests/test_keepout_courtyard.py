"""A keepout that excludes parts is a KiCad rule area, and KiCad's DRC tests each footprint's
courtyard polygon against it (pcbexpr_functions.cpp `collidesWithArea`, via the implicit rule of
drc_engine.cpp), never its body. placemat judges the same shape, whatever `[place] envelope` says:
the envelope decides the spacing between parts, not what a rule area tests."""
import dataclasses
import json
import subprocess

import pytest

from placemat.cutouts import Path
from placemat.layout import Board
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Face, Location, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint

REGION = [(0.0, 0.0), (8.0, 0.0), (8.0, 8.0), (0.0, 8.0)]          # centred at (20, 20): x 16..24
HALF_W, HALF_H = 1.2, 0.7                                          # the courtyard; the body is 0.1 inside it


def _part(envelope):
    fp = footprint("C1", 30, 20, w=2.2, h=1.2, inst="c1", nets=("A", "B"), excess=0.1,
                   silk_boxes=((28.9, 19.4, 31.1, 20.6),))
    ring = ((30 - HALF_W, 20 - HALF_H), (30 + HALF_W, 20 - HALF_H), (30 + HALF_W, 20 + HALF_H), (30 - HALF_W, 20 + HALF_H))
    return dataclasses.replace(fp, courtyard_poly=ring, courtyard_box=type(fp.body_box)(*ring[0], *ring[2]))


def _plan(envelope):
    fp = _part(envelope)
    b = Board(board_geometry([fp], width=40, height=40), edge_margin=0.5, keep_going=True,
              settings=dataclasses.replace(Settings(), place_envelope=envelope))
    b.keepout(Path(REGION), "zone", at=Location(20, 20), excludes=("parts",), why="a case wall")
    return b.resolve(), fp


def _placemat_refuses(plan, fp, x):
    return plan.occupancy.legal(fp, Placement(Location(x, 20.0), 0.0, Face.FRONT), board=True) is not None


# the courtyard's west edge is x - 1.2; the region ends at 24: the body's west edge (x - 1.1) is clear from x = 25.1
@pytest.mark.parametrize("envelope", ["courtyard", "physical", "union"])
def test_a_part_whose_courtyard_is_in_the_region_is_refused_though_its_body_is_clear(envelope):
    plan, fp = _plan(envelope)
    assert _placemat_refuses(plan, fp, 25.15)       # courtyard 0.05 mm inside, body 0.05 mm clear
    assert not _placemat_refuses(plan, fp, 25.25)   # courtyard clear


@needs_kicad
@pytest.mark.parametrize("envelope", ["courtyard", "physical"])
@pytest.mark.parametrize("x", [25.15, 25.25])
def test_placemat_and_kicad_agree_on_the_part(tmp_path, envelope, x):
    import pcbnew
    from placemat.kicad.write import _draw_keepouts
    plan, fp = _plan(envelope)
    board = pcbnew.CreateEmptyBoard()
    mm = lambda a, b: pcbnew.VECTOR2I(pcbnew.FromMM(a), pcbnew.FromMM(b))
    kfp = pcbnew.FOOTPRINT(board)
    kfp.SetReference("C1")
    kfp.SetPosition(mm(x, 20))
    pad = pcbnew.PAD(kfp)
    pad.SetShape(pcbnew.PAD_SHAPE_RECT)
    pad.SetSize(mm(1, 1))
    pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    ls = pcbnew.LSET()
    ls.AddLayer(pcbnew.F_Cu)
    pad.SetLayerSet(ls)
    pad.SetPosition(mm(x, 20))
    kfp.Add(pad)
    crt = pcbnew.PCB_SHAPE(kfp, pcbnew.SHAPE_T_RECT)
    crt.SetStart(mm(x - HALF_W, 20 - HALF_H))
    crt.SetEnd(mm(x + HALF_W, 20 + HALF_H))
    crt.SetLayer(pcbnew.F_CrtYd)
    crt.SetWidth(pcbnew.FromMM(0.05))
    kfp.Add(crt)
    board.Add(kfp)
    _draw_keepouts(board, plan)
    pcb = tmp_path / "layout.kicad_pcb"
    board.Save(str(pcb))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    found = [v for v in json.loads(report.read_text()).get("violations", []) if v.get("type") == "items_not_allowed"]
    assert bool(found) == _placemat_refuses(plan, fp, x), (x, found)


def test_a_searched_part_stands_where_its_courtyard_is_clear_natively_and_in_python(monkeypatch):
    from placemat import geometry, placer
    from placemat.values import Near
    if geometry._native is None:
        pytest.skip("no native module")
    spots = {}
    for on in (False, True):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", on)
        fp = _part("physical")
        b = Board(board_geometry([fp], width=40, height=40), edge_margin=0.5, keep_going=True,
                  settings=dataclasses.replace(Settings(), place_envelope="physical"))
        b.keepout(Path(REGION), "zone", at=Location(20, 20), excludes=("parts",), why="a case wall")
        b.place(Part("c1"), at=Near(Location(25.0, 20), radius=1.0), rotations=(0.0,))
        plan = b.resolve()
        spots[on] = plan.placement("c1")
    assert spots[True] == spots[False]
    assert spots[True].location.x >= 25.2 - 1e-9        # the courtyard's west edge (x - 1.2) reaches the region's at 25.2


def _cell_board(envelope="physical"):
    from placemat.values import Cell
    a, c = _part(envelope), footprint("C2", 33.5, 20, w=2.2, h=1.2, inst="c2", nets=("C", "D"), cell="cc")
    a = dataclasses.replace(a, cell="cc")
    ring = ((33.5 - HALF_W, 20 - HALF_H), (33.5 + HALF_W, 20 - HALF_H), (33.5 + HALF_W, 20 + HALF_H), (33.5 - HALF_W, 20 + HALF_H))
    c = dataclasses.replace(c, courtyard_poly=ring, courtyard_box=type(c.body_box)(*ring[0], *ring[2]))
    b = Board(board_geometry([a, c], cells=["cc"], width=40, height=40), edge_margin=0.5, keep_going=True,
              settings=dataclasses.replace(Settings(), place_envelope=envelope))
    b.keepout(Path(REGION), "zone", at=Location(20, 20), excludes=("parts",), why="a case wall")
    return b, Cell


def test_a_cell_is_judged_by_its_members_courtyards_natively_and_in_python(monkeypatch):
    from placemat import geometry, placer
    from placemat.values import Near
    if geometry._native is None:
        pytest.skip("no native module")
    spots = {}
    for on in (False, True):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", on)
        b, Cell = _cell_board()
        b.place(Cell("cc"), at=Near(Location(25.0, 20), radius=3.0), rotations=(0.0,))
        plan = b.resolve()
        spots[on] = (plan.placement("cc"), plan.occupancy.items["C1"].body)
    assert spots[True] == spots[False]
    assert spots[True][1].left >= 24.1 - 1e-6           # the member's courtyard (0.1 mm outside its body) is clear of the region at 24
    assert spots[True][1].left <= 24.4
