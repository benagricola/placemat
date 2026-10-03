"""A plated hole keeps the board's hole clearance from the copper of another net, a net tie's own
copper bar included. KiCad's DRC_TEST_PROVIDER_COPPER_CLEARANCE::testSingleLayerItemAgainstItem tests
a via's hole (and a pad's) against an item's shape at HOLE_CLEARANCE_CONSTRAINT, and the net-tie rule
that zeroes a copper clearance (DRC_ENGINE::EvalRules) does not reach it."""
import dataclasses
import json
import math
import subprocess

import pytest

from placemat import FreeSpot
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.occupancy import hole_shape
from placemat.values import Box, CopperLayer, Location, Net, PadRef, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint, rect

BAR = rect(19.75, 20.0, 0.5, 0.3)           # x 19.5 to 20.0, y 19.85 to 20.15


def _tie():
    """A stock net tie: two round 0.3 mm pads 0.5 mm apart, pad 1 (net A) at (20, 20), pad 2 (net B) at
    (19.5, 20), joined by a netless bar from pad 2's centre to pad 1's."""
    tie = footprint("NT1", 19.75, 20, w=1.7, h=0.3, inst="nt1", nets=("A", "B"))
    pads = []
    for p, (cx, net) in zip(tie.pads, ((20.0, "A"), (19.5, "B"))):
        disc = circle_polygon(Location(cx, 20.0), 0.15, 32)
        pads.append(dataclasses.replace(p, net=net, outlines=(disc,), box=Box.of_points(disc)))
    return dataclasses.replace(tie, pads=tuple(pads), copper=((CopperLayer.F, BAR),),
                               net_tie_pads=frozenset({"1", "2"}))


def _board(hole_clearance=0.2):
    g = dataclasses.replace(board_geometry([_tie()], width=40, height=40), hole_clearance=hole_clearance)
    b = Board(g, edge_margin=0.5, keep_going=True)
    b.place(Part("nt1"), at=Location(19.75, 20))
    return b


def _hole_gap(at, drill, poly):
    """The drill's edge to the polygon's nearest edge, mm."""
    n = len(poly)
    return min(_seg_dist(at, poly[i], poly[(i + 1) % n]) for i in range(n)) - drill / 2.0


def _seg_dist(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _free_via_plan():
    b = _board()
    b.via(Net("B"), at=FreeSpot(near=PadRef(Part("nt1"), 2)), why="tap")
    return b.resolve()


def test_a_free_spot_via_keeps_its_hole_clear_of_the_net_ties_bar():
    plan = _free_via_plan()
    (via,) = [c for c in plan.copper if type(c).__name__ == "Via"]
    gap = _hole_gap((via.at.x, via.at.y), via.drill, BAR)
    assert gap >= 0.2 - 1e-6, "hole %.3f mm from the bar at %s" % (gap, via.at)


def test_a_hole_too_near_a_net_ties_bar_is_a_conflict_of_the_hole():
    occ = _board().resolve().occupancy
    (why,) = occ.hole_conflicts(hole_shape("", Location(19.5, 20.45), 0.3, "B"))[:1]    # 0.15 mm from the bar
    assert "copper 0.15 mm from a via's hole (needs 0.20)" in str(why) and str(why).startswith("NT1"), why
    assert not occ.hole_conflicts(hole_shape("", Location(19.5, 20.5), 0.3, "B"))       # 0.20 mm


def test_a_hole_centred_in_the_net_ties_pad_of_its_own_net_is_let_through():
    """DRC_ENGINE::IsNetTieExclusion: the hole's position inside a net-tie pad of the hole's net."""
    occ = _board().resolve().occupancy
    on_pad = hole_shape("", Location(19.5, 20.0), 0.3, "B")
    assert not [w for w in occ.hole_conflicts(on_pad) if "bar" in w or "NT1 copper" in w]


def test_a_hole_is_judged_against_netless_copper_and_not_against_its_own_net():
    occ = _board().resolve().occupancy
    at = Location(19.5, 20.45)
    assert occ.hole_conflicts(hole_shape("", at, 0.3, "B"))
    assert occ.hole_conflicts(hole_shape("", at, 0.3, ""))


def _kicad_violations(tmp_path, vias):
    pcbnew = pytest.importorskip("pcbnew")
    mm = pcbnew.FromMM
    board = pcbnew.CreateEmptyBoard()
    board.GetDesignSettings().m_HoleClearance = mm(0.2)
    nets = {}

    def net(n):
        if n not in nets:
            nets[n] = pcbnew.NETINFO_ITEM(board, n)
            board.Add(nets[n])
        return nets[n]
    kfp = pcbnew.FOOTPRINT(board)
    kfp.SetReference("NT1")
    kfp.SetPosition(pcbnew.VECTOR2I(mm(19.75), mm(20.0)))
    for number, cx, n in (("1", 20.0, "A"), ("2", 19.5, "B")):
        kp = pcbnew.PAD(kfp)
        kp.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        kp.SetSize(pcbnew.VECTOR2I(mm(0.3), mm(0.3)))
        kp.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        ls = pcbnew.LSET()
        ls.AddLayer(pcbnew.F_Cu)
        kp.SetLayerSet(ls)
        kp.SetPosition(pcbnew.VECTOR2I(mm(cx), mm(20.0)))
        kp.SetNumber(number)
        kp.SetNet(net(n))
        kfp.Add(kp)
    bar = pcbnew.PCB_SHAPE(kfp)
    bar.SetShape(pcbnew.SHAPE_T_POLY)
    bar.SetLayer(pcbnew.F_Cu)
    bar.SetFilled(True)
    bar.SetWidth(0)
    bar.SetPolyPoints([pcbnew.VECTOR2I(mm(x), mm(y)) for x, y in BAR])
    kfp.Add(bar)
    kfp.AddNetTiePadGroup("1, 2")
    board.Add(kfp)
    for (x, y), drill, size, n in vias:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        v.SetDrill(mm(drill))
        v.SetWidth(pcbnew.F_Cu, mm(size))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetNet(net(n))
        board.Add(v)
    pcb = tmp_path / "tie.kicad_pcb"
    board.Save(str(pcb))
    report = tmp_path / "tie.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    return [v for v in json.loads(report.read_text()).get("violations", []) if v.get("type") == "hole_clearance"]


@needs_kicad
def test_kicad_passes_the_free_spot_via_beside_a_net_tie(tmp_path):
    (via,) = [c for c in _free_via_plan().copper if type(c).__name__ == "Via"]
    assert _kicad_violations(tmp_path, [((via.at.x, via.at.y), via.drill, via.size, "B")]) == []


@needs_kicad
def test_kicad_flags_a_hole_beside_the_bar_as_placemat_does(tmp_path):
    occ = _board().resolve().occupancy
    assert occ.hole_conflicts(hole_shape("", Location(19.5, 20.45), 0.3, "B"))
    flagged = _kicad_violations(tmp_path, [((19.5, 20.45), 0.3, 0.6, "B")])
    assert flagged and "NT1" in json.dumps(flagged), flagged
