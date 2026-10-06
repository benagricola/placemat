"""`reach=Reach.CURRENT` on a fitted pour whose members are vias: a via member is
credited with the current of the pad it joins - the pad a `vias(..., along=PadRef(...))`
row stands out of, or a pad of the net the via stands on - and a pad member with
no copper on the pour's layer, joined to the pour by such a via, is not a refusal.
The case: a receptacle's two VBUS contacts on the outer layer, joined on an inner
layer by a pour over three vias out of each contact.

Plan tests are pure (synthetic four-layer boards); the written-board test builds a
from-scratch pcbnew board and runs `check current-path` on it."""
import dataclasses

import pcbnew
import pytest

from placemat import checks, pourfit
from placemat.board_geometry import Footprint
from placemat.checks import current_paths
from placemat.copper import Pour, Via
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, CopperLayer, Face, Location, Net, PadRef, Part, Reach
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, declared_findings, pad
from tests.test_pour_fitted import CLEARANCE, _vec
from tests.test_pour_reach import _footprint

F, IN1, IN2, B = CopperLayer.F, CopperLayer.IN1, CopperLayer.IN2, CopperLayer.B
FOUR = (F, IN1, IN2, B)
AMPS = 3.0
SHARE = AMPS / 2            # the receptacle's current shared by its two VBUS pads


@pytest.fixture(autouse=True)
def _fab_makes_every_via(monkeypatch):
    monkeypatch.setattr(Board, "fab_via_tiers", {"micro": "yes", "blind": "yes", "buried": "yes"})


def _receptacle(amps):
    """J1: two VBUS contacts, B4A9 west and A4B9 east, 0.6 x 1.2 on the front, its body south of them."""
    pads = (pad("J1", "j1", "B4A9", "VBUS", 10.0, 20.0, 0.6, 1.2), pad("J1", "j1", "A4B9", "VBUS", 15.0, 20.0, 0.6, 1.2))
    body = Box(8.0, 19.0, 17.0, 26.0)
    return Footprint("J1", "j1", None, "J1", body.center, 0.0, Face.FRONT, body, body.inflate(0.1), body, pads,
                     fields={"Pm.I": amps} if amps else {})


def _load(amps):
    """U2: the switch the current goes to, one VBUS pad away from the receptacle."""
    p = pad("U2", "u2", "6", "VBUS", 30.0, 40.0, 1.0, 1.0)
    body = p.box.inflate(0.5)
    return Footprint("U2", "u2", None, "U2", body.center, 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,),
                     fields={"Pm.I": amps} if amps else {})


def _board(receptacle="3A", load="3A", extra=()):
    parts = [_receptacle(receptacle), _load(load)] + list(extra)
    geometry = dataclasses.replace(board_geometry(parts, width=60, height=60, clearance=CLEARANCE), layers=FOUR)
    b = Board(geometry, edge_margin=1.0)
    b.place(Part("j1"), at=Location(12.5, 22.5))
    return b


def _rows(b):
    j = Part("j1")
    return (b.vias(Net("VBUS"), along=PadRef(j, "B4A9"), count=3, size=0.6, drill=0.3),
            b.vias(Net("VBUS"), along=PadRef(j, "A4B9"), count=3, size=0.6, drill=0.3))


def _pour(plan):
    (p,) = [c for c in plan.copper if isinstance(c, Pour)]
    return p


def _reading(plan, amps=AMPS):
    """What `check current-path` reads off the pour between the two via rows, on In2: the vias of each row
    stand in for the contact they come out of."""
    s = Settings()
    vias = [c for c in plan.copper if isinstance(c, Via) and c.net == "VBUS"]
    west = [v for v in vias if v.at.x < 12.5]
    east = [v for v in vias if v.at.x > 12.5]
    assert len(west) == 3 and len(east) == 3
    p = _pour(plan)
    pads = [("J1", "B4A9", v.polygon) for v in west] + [("J1", "A4B9", v.polygon) for v in east]
    return checks.pour_current("VBUS", IN2, pads, [], [pourfit.offset(p.points, p.stroke / 2.0)],
                               {"J1.B4A9": amps, "J1.A4B9": amps}, {}, s.check_rise_c, checks.COPPER_OZ,
                               s.check_zone_step, by_pad=True)


def test_a_pour_over_two_via_rows_is_drawn_and_sized_for_the_contacts_current():
    """Each contact carries the receptacle's 3 A shared by its two VBUS pads: 1.5 A."""
    bare = _board()
    rows = _rows(bare)
    bare.pour(Net("VBUS"), list(rows), layer=IN2, swallow_pads=True)
    narrow = _reading(bare.resolve(), amps=SHARE)
    assert narrow.width < narrow.need               # the hull over the rows alone is too narrow for 1.5 A

    b = _board()
    rows = _rows(b)
    b.pour(Net("VBUS"), list(rows), layer=IN2, swallow_pads=True, reach=Reach.CURRENT)
    plan = b.resolve()
    assert not [f for f in declared_findings(plan) if f.startswith("pour")], plan.findings
    assert _pour(plan).layer is IN2
    got = _reading(plan, amps=SHARE)
    assert got.width >= got.need and got.amps == pytest.approx(SHARE)


def test_the_contacts_with_the_via_rows_are_drawn_too():
    b = _board()
    west, east = _rows(b)
    j = Part("j1")
    b.pour(Net("VBUS"), [PadRef(j, "B4A9"), west, east, PadRef(j, "A4B9")], layer=IN2, swallow_pads=True,
           reach=Reach.CURRENT)
    plan = b.resolve()
    assert not [f for f in declared_findings(plan) if f.startswith("pour")], plan.findings
    got = _reading(plan, amps=SHARE)
    assert got.width >= got.need


def test_the_current_is_the_parts_own_rating_shared_by_its_pads_whatever_the_load():
    b = _board(receptacle="3A", load="0.5A")
    b.pour(Net("VBUS"), list(_rows(b)), layer=IN2, swallow_pads=True, reach=Reach.CURRENT)
    plan = b.resolve()
    assert not [f for f in declared_findings(plan) if f.startswith("pour")], plan.findings
    got = _reading(plan, amps=SHARE)
    assert got.width >= got.need and got.amps == pytest.approx(SHARE)


def test_via_rows_out_of_a_part_that_carries_no_current_are_the_none_carries_finding():
    others = [dataclasses.replace(_load("3A"), ref="U5", inst="u5", pads=(pad("U5", "u5", "1", "VBUS", 40.0, 10.0),)),
              dataclasses.replace(_load("3A"), ref="U6", inst="u6", pads=(pad("U6", "u6", "1", "VBUS", 40.0, 20.0),))]
    b = _board(receptacle=None, load=None, extra=others)
    b.pour(Net("VBUS"), list(_rows(b)), layer=IN2, swallow_pads=True, reach=Reach.CURRENT)
    plan = b.resolve()
    assert not [c for c in plan.copper if isinstance(c, Pour)]
    assert any(f.startswith("pour VBUS") and "none of its pads' parts carries current on VBUS" in f
               for f in declared_findings(plan)), plan.findings


def test_via_rows_on_a_net_with_no_current_are_refused():
    b = _board(receptacle=None, load=None)
    with pytest.raises(ValueError, match="no part carries current"):
        b.pour(Net("VBUS"), list(_rows(b)), layer=IN2, swallow_pads=True, reach=Reach.CURRENT)


def test_a_pad_off_the_layer_with_no_via_joining_it_is_still_refused():
    b = _board()
    west, _ = _rows(b)
    b.pour(Net("VBUS"), [west, PadRef(Part("j1"), "A4B9")], layer=IN2, swallow_pads=True)
    plan = b.resolve()
    assert not [c for c in plan.copper if isinstance(c, Pour)]
    assert any("pad J1.A4B9 has no copper on In2.Cu" in f for f in declared_findings(plan)), plan.findings


def test_a_via_standing_on_a_pad_is_credited_with_its_part():
    b = _board()
    j = Part("j1")
    on_west = b.via(Net("VBUS"), PadRef(j, "B4A9"), size=0.5, drill=0.25)
    on_east = b.via(Net("VBUS"), PadRef(j, "A4B9"), size=0.5, drill=0.25)
    b.pour(Net("VBUS"), [PadRef(j, "B4A9"), on_west, on_east, PadRef(j, "A4B9")], layer=IN2, swallow_pads=True,
           reach=Reach.CURRENT)
    plan = b.resolve()
    assert [c for c in plan.copper if isinstance(c, Pour)], plan.findings
    assert not [f for f in declared_findings(plan) if f.startswith("pour")], plan.findings


# ---------------------------------------------------------------- written board


def _written(tmp_path):
    """J1's two VBUS contacts on the front and U2's pad, joined by a front track from B4A9 wide enough for 3 A, on a
    four-layer 50 mm board."""
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(4)
    b.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(pcbnew.FromMM(CLEARANCE))
    for a, c in (((0, 0), (50, 0)), ((50, 0), (50, 50)), ((50, 50), (0, 50)), ((0, 50), (0, 0))):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(_vec(*a))
        s.SetEnd(_vec(*c))
        b.Add(s)
    nets = {"VBUS": pcbnew.NETINFO_ITEM(b, "VBUS")}
    b.Add(nets["VBUS"])
    _footprint(b, "J1", nets, [("B4A9", "VBUS", 10.0, 20.0, 0.6, 1.2), ("A4B9", "VBUS", 15.0, 20.0, 0.6, 1.2)],
               {"Pm.I": "3A"})
    _footprint(b, "U2", nets, [("6", "VBUS", 10.0, 30.0, 2.0, 2.0)], {"Pm.I": "3A"})
    t = pcbnew.PCB_TRACK(b)
    t.SetLayer(pcbnew.F_Cu)
    t.SetWidth(pcbnew.FromMM(2.0))
    t.SetStart(_vec(10.0, 20.0))
    t.SetEnd(_vec(10.0, 30.0))
    t.SetNet(nets["VBUS"])
    b.Add(t)
    path = tmp_path / "vbus.kicad_pcb"
    b.Save(str(path))
    return path


@needs_kicad
def test_the_written_pour_passes_current_path(tmp_path):
    pcb = _written(tmp_path)
    board = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    board.rect(width=50.0, height=50.0)
    j = Part("J1")
    west = board.vias(Net("VBUS"), along=PadRef(j, "B4A9"), count=3, size=0.6, drill=0.3)
    east = board.vias(Net("VBUS"), along=PadRef(j, "A4B9"), count=3, size=0.6, drill=0.3)
    board.pour(Net("VBUS"), [west, east], layer=IN2, swallow_pads=True, reach=Reach.CURRENT)
    plan = board.resolve()
    assert not [f for f in declared_findings(plan) if f.startswith("pour")], plan.findings
    assert [c for c in plan.copper if isinstance(c, Pour) and c.layer is IN2]
    apply_plan(pcb, plan)
    v = {x.subject: x for x in current_paths(read_board(pcb))}["VBUS"]
    assert v.ok is True, v
