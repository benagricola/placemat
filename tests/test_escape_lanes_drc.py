"""The north-row model's lanes, risers and vias are clean in KiCad's DRC: placemat's own clearance arithmetic
(the lanes' steps, the vias' first legal spots) and kicad-cli agree on a board that carries the QFN's pads and
the copper the escape drew."""
import json
import subprocess

import pytest

from placemat.copper import Track, Via
from placemat.values import CopperLayer, Edge, Net, Part
from tests.conftest import needs_kicad
from tests.escape_fixtures import pd_board

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")

F = CopperLayer.F
CHECKED = ("clearance", "hole_clearance", "hole_to_hole", "shorting_items", "tracks_crossing")


def _mm(v):
    return pcbnew.FromMM(v)


def _violations(tmp_path, plan, name, extra=(), kinds=CHECKED, clearance=None):
    """The violations of `kinds` (CHECKED unless said; "unconnected_items" reads that section) that kicad-cli reports on a
    board carrying `plan`'s parts' pads and copper (and the tracks of `extra`), judged by the default 0.2 mm netclass or by
    `clearance` (mm) as the default class's."""
    board = pcbnew.CreateEmptyBoard()
    nets = {}

    def net(n):
        if n not in nets:
            nets[n] = pcbnew.NETINFO_ITEM(board, n)
            board.Add(nets[n])
        return nets[n]
    for fp in plan.geometry.footprints:
        kfp = pcbnew.FOOTPRINT(board)
        kfp.SetReference(fp.ref)
        kfp.SetPosition(pcbnew.VECTOR2I(_mm(fp.location.x), _mm(fp.location.y)))
        for p in fp.pads:
            kp = pcbnew.PAD(kfp)
            kp.SetShape(pcbnew.PAD_SHAPE_RECT)
            kp.SetSize(pcbnew.VECTOR2I(_mm(p.box.width), _mm(p.box.height)))
            kp.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            ls = pcbnew.LSET()
            ls.AddLayer(pcbnew.F_Cu)
            kp.SetLayerSet(ls)
            kp.SetPosition(pcbnew.VECTOR2I(_mm(p.box.center.x), _mm(p.box.center.y)))
            kp.SetNumber(str(p.number))
            kp.SetNet(net(p.net))
            kfp.Add(kp)
        board.Add(kfp)
    for t in [op for op in plan.copper if isinstance(op, Track)] + list(extra):
        kt = pcbnew.PCB_TRACK(board)
        kt.SetLayer(pcbnew.F_Cu)
        kt.SetWidth(_mm(t.width))
        kt.SetStart(pcbnew.VECTOR2I(_mm(t.start.x), _mm(t.start.y)))
        kt.SetEnd(pcbnew.VECTOR2I(_mm(t.end.x), _mm(t.end.y)))
        kt.SetNet(net(t.net))
        board.Add(kt)
    for v in (op for op in plan.copper if isinstance(op, Via)):
        kv = pcbnew.PCB_VIA(board)
        kv.SetViaType(pcbnew.VIATYPE_THROUGH)
        kv.SetPosition(pcbnew.VECTOR2I(_mm(v.at.x), _mm(v.at.y)))
        kv.SetWidth(_mm(v.size))
        kv.SetDrill(_mm(v.drill))
        kv.SetNet(net(v.net))
        board.Add(kv)
    pcb = tmp_path / ("%s.kicad_pcb" % name)
    board.Save(str(pcb))
    if clearance is not None:
        (tmp_path / ("%s.kicad_dru" % name)).write_text(
            '(version 1)\n(rule "clearance" (constraint clearance (min %smm)))\n' % clearance)
    report = tmp_path / ("%s.json" % name)
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    data = json.loads(report.read_text())
    return [v for v in data.get("violations", []) + data.get("unconnected_items", []) if v.get("type") in kinds]


def _north_row_plan():
    b = pd_board()
    esc = b.escape(Part("pd"), [32, 31, 30], turn=Edge.WEST, vias=[31, 30], widths={32: 0.3}, why="north row")
    for pin, net in ((32, "VOUT"), (31, "SENSE"), (30, "PGOOD")):
        b.track(Net(net), [esc[pin]], layer=F, why="its lane")
    return b.resolve()


def test_the_written_north_row_passes_kicads_drc(tmp_path):
    plan = _north_row_plan()
    assert [op for op in plan.copper if isinstance(op, Via)]
    assert _violations(tmp_path, plan, "north_row") == []


def test_kicads_drc_does_flag_a_track_a_hair_inside_a_lane(tmp_path):
    plan = _north_row_plan()
    lane = next(op for op in plan.copper if isinstance(op, Track) and op.net == "PGOOD" and op.start.y == op.end.y)
    y = lane.start.y - (0.1 + 0.1 + 0.19)                   # north of the outermost lane: 0.19 mm off its edge, under 0.2
    intruder = Track("N29", F, 0.2, type(lane.start)(lane.start.x - 0.2, y), type(lane.start)(lane.start.x - 0.4, y))
    assert _violations(tmp_path, plan, "intruder", extra=[intruder])       # the check is a real one
