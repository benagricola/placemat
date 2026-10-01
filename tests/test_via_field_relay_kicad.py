"""The write does to a stamped cell's group what a field's relay decided (giveway_field.write): a via
moved, taken out or added, each found where it was drawn before any is changed; and kicad-cli's DRC
finds the re-laid field clear of the other face's pad where the field as drawn is not."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from placemat.giveway_field import FieldStep
from placemat.settings import Settings
from tests.conftest import needs_kicad
from tests.test_via_field_relay import FIELD, NO_LEAVE, SHIFT, TOP_ROW, _board, _placed

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")


def _mm(v):
    return pcbnew.FromMM(v)


def _vec(x, y):
    return pcbnew.VECTOR2I(_mm(x), _mm(y))


def _cell_board(vias):
    """A board with a GND net and group "m" holding a via at each of `vias` (placed coordinates)."""
    board = pcbnew.CreateEmptyBoard()
    net = pcbnew.NETINFO_ITEM(board, "GND")
    board.Add(net)
    group = pcbnew.PCB_GROUP(board)
    group.SetName("m")
    board.Add(group)
    for x, y in vias:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(_vec(x, y))
        v.SetWidth(_mm(0.45))
        v.SetDrill(_mm(0.2))
        v.SetNet(net)
        board.Add(v)
        group.AddItem(v)
    return board, group, net


def _vias(group):
    return sorted((round(v.GetPosition().x / 1e6, 3), round(v.GetPosition().y / 1e6, 3))
                  for v in group.GetItems() if isinstance(v, pcbnew.PCB_VIA))


def _drawn():
    return [(round(x - SHIFT, 3), round(y - SHIFT, 3)) for x, y in FIELD]


def test_a_relay_moves_the_vias_of_a_cells_group_where_it_decided():
    from placemat.kicad.write import _given_way
    plan = _board(FIELD, [TOP_ROW], settings=NO_LEAVE).resolve()
    board, group, _ = _cell_board(_drawn())
    _given_way(board, SimpleNamespace(given_way=list(plan.occupancy.given_way.values())), {"m": group})
    assert _vias(group) == _placed(plan)


def test_a_relay_adds_a_via_like_its_neighbours_and_takes_another_out():
    from placemat.kicad.write import _given_way
    board, group, _ = _cell_board([(10.0, 10.0), (10.6, 10.0), (11.2, 10.0)])
    common = dict(owner="m", home="m", net="GND", field="field m U1.1", way="shift vias", before=3, after=3, want=3)
    steps = [FieldStep(kind="relay-drop", via="m via 0", at=(10.0, 10.0), **common),
             FieldStep(kind="relay-add", via="m relay 0", at=(11.8, 10.0), to=(11.8, 10.0), **common),
             FieldStep(kind="relay-move", via="m via 2", at=(11.2, 10.0), to=(11.2, 10.6), **common)]
    _given_way(board, SimpleNamespace(given_way=steps), {"m": group})
    assert _vias(group) == [(10.6, 10.0), (11.2, 10.6), (11.8, 10.0)]
    assert {(v.GetWidth(), v.GetDrill()) for v in group.GetItems()} == {(_mm(0.45), _mm(0.2))}
    assert {v.GetNetname() for v in group.GetItems()} == {"GND"}
    assert len([v for v in board.GetTracks()]) == 3             # the board holds each of them, no more


_RULES = {"clearance", "hole_clearance", "hole_to_hole", "shorting_items"}


def _violations(tmp_path, vias):
    """kicad-cli's clearance and hole violations of a board with the cell's pad on the front, R9's on the back, and `vias`."""
    board, group, net = _cell_board(vias)
    other = pcbnew.NETINFO_ITEM(board, "S")
    board.Add(other)

    def pad_fp(ref, net_, layer, cx, cy, w, h):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPosition(_vec(cx, cy))
        p = pcbnew.PAD(fp)
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetSize(pcbnew.VECTOR2I(_mm(w), _mm(h)))
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        ls = pcbnew.LSET()
        ls.AddLayer(layer)
        p.SetLayerSet(ls)
        p.SetPosition(_vec(cx, cy))
        p.SetNumber("1")
        p.SetNet(net_)
        fp.Add(p)
        board.Add(fp)
    pad_fp("U1", net, pcbnew.F_Cu, 38.1 - SHIFT, 40.0 - SHIFT, 2.6, 3.0)
    pad_fp("R9", other, pcbnew.B_Cu, TOP_ROW[0], TOP_ROW[1], TOP_ROW[2], TOP_ROW[3])
    pcb = tmp_path / "board.kicad_pcb"
    board.Save(str(pcb))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   check=True, capture_output=True)
    return [v for v in json.loads(report.read_text())["violations"] if v["type"] in _RULES]


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="no kicad-cli")
def test_kicad_finds_the_relaid_field_clear_of_the_other_faces_pad_and_the_drawn_one_not(tmp_path):
    from placemat.kicad.write import _given_way
    plan = _board(FIELD, [TOP_ROW], settings=NO_LEAVE).resolve()
    board, group, _ = _cell_board(_drawn())
    _given_way(board, SimpleNamespace(given_way=list(plan.occupancy.given_way.values())), {"m": group})
    after = _vias(group)
    assert len(after) == 9
    assert _violations(tmp_path, after) == []
    assert _violations(tmp_path, _drawn()) != []             # the control: the field as drawn meets the pad
