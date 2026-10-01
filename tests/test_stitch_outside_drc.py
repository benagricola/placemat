"""Stitching vias outside a region's edge, written to a board and judged by kicad-cli's DRC: no clearance
or hole violation against another net's pad, and none between the vias' own holes."""
import json
import subprocess

import pytest

from placemat.copper import Via
from placemat.cutouts import Path
from placemat.layout import Board
from placemat.values import Edge, Location, Net, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint
from tests.test_vias_along_and_stitch import RECT

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")

_RULES = {"clearance", "hole_clearance", "hole_to_hole", "via_diameter", "annular_width", "drill_out_of_range"}


def _mm(v):
    return pcbnew.FromMM(v)


def _violations(tmp_path, plan, extra_vias=()):
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
    for v in [o for o in plan.copper if isinstance(o, Via)] + list(extra_vias):
        kv = pcbnew.PCB_VIA(board)
        kv.SetPosition(pcbnew.VECTOR2I(_mm(v.at.x), _mm(v.at.y)))
        kv.SetWidth(_mm(v.size))
        kv.SetDrill(_mm(v.drill))
        kv.SetNet(net(v.net))
        board.Add(kv)
    pcb = tmp_path / "board.kicad_pcb"
    board.Save(str(pcb))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    return [v for v in json.loads(report.read_text()).get("violations", []) if v.get("type") in _RULES]


def _plan(pad_at):
    other = footprint("T1", pad_at[0], pad_at[1], w=4, h=2, inst="t1", nets=("OTHER", "OTHER"))
    b = Board(board_geometry([other], width=60, height=60, extra_nets=["GND"]), edge_margin=1.0, keep_going=True)
    b.place(Part("t1"), at=Location(*pad_at))
    b.keepout(Path(RECT), "clearance", at=Location(30, 30), why="probe")
    b.stitch(Net("GND"), "clearance", edge=True, outside=True, hole_to_edge=0.35, pitch=2.0,
             sides=[Edge.EAST, Edge.SOUTH], size=0.6, drill=0.3, why="probe")
    return b.resolve()


def test_kicad_finds_no_clearance_or_hole_violation_in_the_outside_row(tmp_path):
    plan = _plan((37.0, 29.0))              # a pad of another net beside the east row: the via it blocks is left out
    assert len([o for o in plan.copper if isinstance(o, Via)]) == 8      # 4 + 6 - 1 shared corner, less the east via the pad blocks
    assert _violations(tmp_path, plan) == []


def test_kicad_flags_a_via_too_near_the_pad_as_a_control(tmp_path):
    plan = _plan((37.0, 29.0))
    blocked = Via("GND", Location(35.5, 29.9), 0.3, 0.6, ())
    assert _violations(tmp_path, plan, [blocked])           # 0.1 mm from the pad: KiCad does judge the clearance the row keeps
