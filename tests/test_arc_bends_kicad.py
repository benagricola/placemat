"""Arc corners written to KiCad (docs/superpowers/specs/2026-10-02-arc-bends-design.md): PCB_ARC
tracks joined end to end, kicad-cli's DRC clean on them, its clearance verdict the same as
placemat's for a pad the arc meets and one the chamfer meets, and the board read back and
measured with its arcs counted along the arc."""
import json
import math
import shutil
import subprocess

import pytest

from placemat import describe
from placemat.copper import Track
from placemat.kicad import write
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Bend, CopperLayer, Location, Net, PadRef, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry
from tests.test_arc_bends import _pad_at

pytestmark = [needs_kicad, pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="no kicad-cli")]

pcbnew = pytest.importorskip("pcbnew")

F = CopperLayer.F
W = 0.3
START, END = (8.6, 10.0), (30.0, 20.0)                 # the track's pads
V = (20.0, 10.0)                                        # its first corner


def _mm(v):
    return pcbnew.FromMM(v)


def _vec(x, y):
    return pcbnew.VECTOR2I(_mm(x), _mm(y))


def _plan(waypoints, extra=(), clearance=0.2, **track):
    pads = [_pad_at("R0", START[0], START[1], "A", 0.6), _pad_at("R9", END[0], END[1], "A", 0.6)]
    g = board_geometry(pads + list(extra), width=60, height=60, clearance=clearance, extra_nets=("B",))
    b = Board(g, edge_margin=0.5, keep_going=True, settings=Settings())
    for fp in pads + list(extra):
        b.place(Part(fp.inst), at=fp.location)
    b.track(Net("A"), [PadRef(Part("r0"), 1)] + list(waypoints) + [PadRef(Part("r9"), 1)], layer=F, width=W, **track)
    return b.resolve()


def _write(tmp_path, plan, extra=(), clearance=0.2, name="board"):
    board = pcbnew.CreateEmptyBoard()
    board.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(_mm(clearance))
    nets = {n: pcbnew.NETINFO_ITEM(board, n) for n in ("A", "B")}
    for n in nets.values():
        board.Add(n)
    for a, c in (((0, 0), (60, 0)), ((60, 0), (60, 60)), ((60, 60), (0, 60)), ((0, 60), (0, 0))):
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(_vec(*a))
        s.SetEnd(_vec(*c))
        board.Add(s)
    for k, (ref, net, x, y, size) in enumerate([("R0", "A", *START, 0.6), ("R9", "A", *END, 0.6)] + list(extra)):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.Reference().SetVisible(False)
        fp.SetPosition(_vec(x, y))
        p = pcbnew.PAD(fp)
        p.SetNumber("1")
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetSize(pcbnew.VECTOR2I(_mm(size), _mm(size)))
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetLayerSet(pcbnew.PAD.SMDMask())
        p.SetPosition(_vec(x, y))
        p.SetNet(nets[net])
        fp.Add(p)
        board.Add(fp)
    write.draw_copper(board, [op for op in plan.copper if isinstance(op, Track)])
    pcb = tmp_path / (name + ".kicad_pcb")
    board.Save(str(pcb))
    return pcb, board


def _drc(pcb):
    report = pcb.with_suffix(".json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   check=True, capture_output=True)
    doc = json.loads(report.read_text())
    return [v["type"] for v in doc["violations"]], [v["type"] for v in doc.get("unconnected_items", [])]


def _kinds(board):
    return [("arc" if isinstance(t, pcbnew.PCB_ARC) else "track") for t in board.GetTracks()]


WAYPOINTS = [(20.0, 10.0), (20.0, 20.0)]


def test_a_track_with_two_corners_is_written_as_two_arcs_between_three_straights(tmp_path):
    plan = _plan(WAYPOINTS, bend=Bend.ARC)
    pcb, board = _write(tmp_path, plan)
    assert _kinds(board) == ["track", "arc", "track", "arc", "track"]


def test_kicad_finds_the_arc_track_clear_connected_and_with_nothing_dangling(tmp_path):
    plan = _plan(WAYPOINTS, bend=Bend.ARC)
    pcb, _ = _write(tmp_path, plan)
    violations, unconnected = _drc(pcb)
    assert violations == [] and unconnected == []


def test_the_arcs_are_the_planned_circles_and_join_the_legs_at_one_point(tmp_path):
    plan = _plan(WAYPOINTS, bend=Bend.ARC)
    pcb, board = _write(tmp_path, plan)
    arcs = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_ARC)]
    assert len(arcs) == 2
    for t in arcs:
        assert t.GetRadius() / 1e6 == pytest.approx(4 * W, abs=2e-4)
    ts = sorted(board.GetTracks(), key=lambda t: (t.GetStart().x, t.GetStart().y))
    ends = {(t.GetStart().x, t.GetStart().y) for t in ts} | {(t.GetEnd().x, t.GetEnd().y) for t in ts}
    starts = [(t.GetStart().x, t.GetStart().y) for t in ts]
    assert len(ends) == len(ts) + 1 and all(s in ends for s in starts)       # each joint is shared: a chain of five


def test_read_back_the_length_is_along_the_arcs_and_matches_the_plan(tmp_path):
    from placemat.kicad.read import read_board
    plan = _plan(WAYPOINTS, bend=Bend.ARC)
    pcb, _ = _write(tmp_path, plan)
    planned = sum(op.length for op in plan.copper if isinstance(op, Track))
    g = read_board(pcb)
    got = sum(c.length_mm for c in g.copper if c.kind == "track")
    assert got == pytest.approx(planned, abs=5e-4)
    chord = sum(math.dist(*c.anchors) for c in g.copper if c.kind == "track")
    assert got < chord + 1.0 and got > chord - 1e-6 and got != pytest.approx(chord, abs=1e-3)   # the arcs are longer than their chords


def test_measure_copper_calls_the_arcs_arcs_and_flags_none_off_0_45_90(tmp_path):
    from placemat.kicad.read import read_board
    plan = _plan(WAYPOINTS, bend=Bend.ARC)
    pcb, _ = _write(tmp_path, plan)
    segs = describe.copper_segments(read_board(pcb), [])
    assert [s["arc"] for s in sorted(segs, key=lambda s: s["start"])] == [False, True, False, True, False]
    assert all(s["octilinear"] for s in segs)
    line = "\n".join(describe.copper_lines(read_board(pcb), []))
    assert line.count(" arc") == 2 and "off 0/45/90" not in line


# a 0.2 mm pad centred on the first corner: the arc hugs the corner (0.20 mm off) and the chamfer
# cuts it away (0.42 mm off); under a 0.3 mm rule only the arc is too near it
OUTSIDE = ("R1", "B", V[0], V[1], 0.2)
# a pad inside the turn, on the corner's bisector 0.6 mm from the arc's centre: the chamfer's 45 cuts
# across to 0.10 mm of it, the arc stays 0.31 mm off
C = (18.8, 11.2)
s = math.sqrt(0.5)
INSIDE = ("R1", "B", C[0] + 0.6 * s, C[1] - 0.6 * s, 0.2)


@pytest.mark.parametrize("pad,clearance,arc_meets,chamfer_meets", [(OUTSIDE, 0.3, True, False),
                                                                    (INSIDE, 0.2, False, True)])
def test_kicads_clearance_verdict_on_a_pad_is_placemats_for_the_arc_and_for_the_chamfer(
        tmp_path, pad, clearance, arc_meets, chamfer_meets):
    near = _pad_at(*pad[:1], pad[2], pad[3], pad[1], pad[4])
    for label, kw, meets in (("arc", {"bend": Bend.ARC}, arc_meets), ("chamfer", {}, chamfer_meets)):
        plan = _plan(WAYPOINTS, extra=[near], clearance=clearance, **kw)
        pcb, _ = _write(tmp_path, plan, extra=[pad], clearance=clearance, name=label)
        violations, _ = _drc(pcb)
        kicad = "clearance" in violations
        placemat = any(f.kind == "copper" and " is " in str(f) and "mm from B copper" in str(f) for f in plan.findings)
        assert kicad == meets == placemat, (label, violations, [str(f) for f in plan.findings])
