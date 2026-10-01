"""Beside(item, side, copper=True, gap=, align=): a part stands as near `item` on
`side` as its pads allow, every pad keeping the clearance its pair needs (and
`gap`) from every pad of another net, measured copper to copper. Synthetic
boards, and KiCad's DRC over a written one."""
import json
import shutil
import subprocess

import pytest

from placemat.geometry import poly_distance
from placemat.layout import Board
from placemat.reuse import canonical
from placemat.values import Beside, Cell, Edge, Location, Net, PadRef, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint
from tests.test_pad_on_pad_edge import _board, _own, _shunt, _tie

CLEARANCE = 0.16


def _pads(plan, ref, number):
    return [s for s in plan.occupancy.items[ref].shapes if s.kind in ("pad", "through") and s.label == str(number)]


def _gap(plan, a, b):
    """The copper distance between pad `a` and pad `b`, each a (ref, number)."""
    return min(poly_distance(p.poly, q.poly) for p in _pads(plan, *a) for q in _pads(plan, *b))


def _tie_beside_shunt(rotation=0, nets=("V_HI", "SENSE"), courtyard=False, rule=None, **kw):
    b = _board([_shunt(), _tie("NT1", nets, courtyard)])
    if rule:
        b.rule(**rule)
    b.place(Part("rs"), at=Location(30, 30), rotation=0)
    b.place(Part("nt1"), at=Beside(Part("rs"), Edge.NORTH, copper=True, align=(1, PadRef(Part("rs"), 1)), **kw),
            rotation=rotation)
    return b.resolve()


def test_a_net_tie_stands_a_clearance_off_the_pad_of_another_net_copper_to_copper():
    plan = _tie_beside_shunt()
    assert _gap(plan, ("NT1", 2), ("RS", 1)) == pytest.approx(CLEARANCE, abs=1e-4)
    assert _pads(plan, "NT1", 1)[0].box.center.x == pytest.approx(30.0, abs=1e-6)     # on the V_HI pad's centre line
    assert not _own(plan), plan.findings


def test_gap_is_added_to_the_clearance():
    plan = _tie_beside_shunt(gap=0.1)
    assert _gap(plan, ("NT1", 2), ("RS", 1)) == pytest.approx(CLEARANCE + 0.1, abs=1e-4)


def test_a_nearer_pad_of_the_same_net_sets_no_distance():
    """Turned so pad 1 (the item pad's own net) is the nearer: the standoff is pad 2's, further out."""
    plan = _tie_beside_shunt(rotation=90)
    near, far = _pads(plan, "NT1", 1)[0].box.center, _pads(plan, "NT1", 2)[0].box.center
    assert near.y > far.y                                  # pad 1 is the south pad, nearer the item
    assert _gap(plan, ("NT1", 2), ("RS", 1)) == pytest.approx(CLEARANCE, abs=1e-4)
    assert _gap(plan, ("NT1", 1), ("RS", 1)) == 0.0        # it overlaps its own net's pad


def test_a_board_rule_clearance_for_the_pair_is_kept():
    plan = _tie_beside_shunt(rule=dict(clearance=0.4, between=(Net("V_HI"), Net("SENSE")), why="the pair needs more"))
    assert _gap(plan, ("NT1", 2), ("RS", 1)) == pytest.approx(0.4, abs=1e-4)


def test_a_round_pad_standing_past_a_corner_gets_its_true_standoff():
    """Pad 2 lies 0.1 mm beyond the item pad's east side: its round copper is nearest the corner, not the side."""
    b = _board([_shunt(), _tie("NT1", ("V_HI", "SENSE")), footprint("R9", 32.1, 10, w=4, h=2, inst="r9",
                                                                           nets=("X", "Y"))])
    b.place(Part("rs"), at=Location(30, 30), rotation=0)
    b.place(Part("r9"), at=Location(32.1, 10), rotation=0)
    b.place(Part("nt1"), at=Beside(Part("rs"), Edge.NORTH, copper=True, align=(2, PadRef(Part("r9"), 1))), rotation=0)
    plan = b.resolve()
    assert _pads(plan, "NT1", 2)[0].box.center.x == pytest.approx(30.7, abs=1e-6)
    assert _gap(plan, ("NT1", 2), ("RS", 1)) == pytest.approx(CLEARANCE, abs=1e-4)
    # the straight-down standoff would be 0.16 off the side; past the corner it is nearer
    assert _pads(plan, "NT1", 2)[0].box.bottom > 28.05 - CLEARANCE


def test_a_body_overlapping_the_items_at_the_copper_distance_is_refused_naming_both():
    plan = _tie_beside_shunt(courtyard=True)
    assert [f for f in plan.findings if "NT1" in f and "RS" in f], plan.findings


def test_a_cell_item_is_measured_from_its_members_pads():
    fps = [footprint("U1", 0, 0, w=4, h=2, inst="pd.u1", nets=("A", "B"), cell="pd"), _tie("NT1", ("A", "S"))]
    b = Board(board_geometry(fps, cells=["pd"], width=60, height=60), edge_margin=1.0)
    b.place(Cell("pd"), at=Location(20, 20))
    b.place(Part("nt1"), at=Beside(Cell("pd"), Edge.NORTH, copper=True, align=(2, PadRef(Part("pd.u1"), 2))), rotation=0)
    plan = b.resolve()
    assert min(_gap(plan, ("NT1", n), ("U1", 2)) for n in (1, 2)) == pytest.approx(0.2, abs=1e-4)


def test_a_part_with_no_pad_facing_a_pad_of_another_net_is_refused():
    b = _board([footprint("R1", 30, 30, w=4, h=2, inst="r1", nets=("A", "A")), _tie("NT1", ("A", "B"))])
    b.place(Part("r1"), at=Location(30, 30), rotation=0)
    b.place(Part("nt1"), at=Beside(Part("r1"), Edge.NORTH, copper=True), rotation=90)
    with pytest.raises(ValueError, match="copper=True"):
        b.resolve()


def test_a_keepout_has_no_copper_to_stand_off():
    from placemat.cutouts import Path
    b = _board([_shunt()])
    k = b.keepout(Path([(-3.0, -2.0), (3.0, -2.0), (3.0, 2.0), (-3.0, 2.0)]), "clr", at=Location(20.0, 20.0), why="x")
    with pytest.raises(TypeError, match="copper"):
        b.place(Part("rs"), at=Beside(k, Edge.EAST, copper=True))


def test_without_copper_the_declaration_and_the_placement_are_as_before():
    assert "copper" not in str(canonical(Beside(Part("rs"), Edge.NORTH, gap=0.1)))
    assert "copper" in str(canonical(Beside(Part("rs"), Edge.NORTH, copper=True)))
    b = _board([_shunt(), _tie("NT1", ("V_HI", "SENSE"))])
    b.place(Part("rs"), at=Location(30, 30), rotation=0)
    b.place(Part("nt1"), at=Beside(Part("rs"), Edge.NORTH, align=(1, PadRef(Part("rs"), 1))), rotation=0)
    plan = b.resolve()
    # the envelopes (pads and bar here) stand a gap apart, not a copper clearance
    assert _gap(plan, ("NT1", 2), ("RS", 1)) != pytest.approx(CLEARANCE, abs=1e-3)


@needs_kicad
def test_the_written_board_passes_kicads_drc(tmp_path):
    """A stock net tie north of an upright shunt, pad 1 on the output pad's centre line: through pcbnew, placemat
    and the writer, kicad-cli's DRC finds no clearance or shorting item."""
    import pcbnew
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    board = pcbnew.CreateEmptyBoard()
    board.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(pcbnew.FromMM(CLEARANCE))
    v = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
    nets = {}
    for name in ("VOUT", "VIN", "SENSE"):
        nets[name] = pcbnew.NETINFO_ITEM(board, name)
        board.Add(nets[name])
    for a, c in (((0, 0), (40, 0)), ((40, 0), (40, 40)), ((40, 40), (0, 40)), ((0, 40), (0, 0))):
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(v(*a))
        s.SetEnd(v(*c))
        board.Add(s)

    def part(ref, at, pads):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPosition(v(*at))
        board.Add(fp)
        for number, net, x, y, w, h, shape in pads:
            p = pcbnew.PAD(fp)
            p.SetNumber(str(number))
            p.SetShape(shape)
            p.SetSize(v(w, h))
            p.SetPosition(v(x, y))
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            p.SetLayerSet(pcbnew.PAD.SMDMask())
            p.SetNet(nets[net])
            fp.Add(p)
        return fp

    # an upright 1206-size shunt: the output pad north, 1.2 wide and 1.57 tall, 0.76 from the input pad
    part("RS", (10, 30), ((1, "VOUT", 10, 28.835, 1.2, 1.57, pcbnew.PAD_SHAPE_RECT),
                          (2, "VIN", 10, 31.165, 1.2, 1.57, pcbnew.PAD_SHAPE_RECT)))
    tie = part("NT", (20, 20), ((1, "VOUT", 20, 20, 0.3, 0.3, pcbnew.PAD_SHAPE_CIRCLE),
                                (2, "SENSE", 20.5, 20, 0.3, 0.3, pcbnew.PAD_SHAPE_CIRCLE)))
    bar = pcbnew.PCB_SHAPE(tie, pcbnew.SHAPE_T_POLY)
    bar.SetLayer(pcbnew.F_Cu)
    bar.SetFilled(True)
    bar.SetWidth(0)
    pts = pcbnew.VECTOR_VECTOR2I()
    for x, y in ((20, 19.85), (20.5, 19.85), (20.5, 20.15), (20, 20.15)):
        pts.append(v(x, y))
    bar.SetPolyPoints(pts)
    tie.Add(bar)
    tie.AddNetTiePadGroup("1, 2")
    pcb = tmp_path / "in.kicad_pcb"
    board.Save(str(pcb))

    layout = Board(read_board(str(pcb)), edge_margin=0.5, keep_going=True)
    layout.size(width=40.0, height=40.0)
    layout.place(Part("RS"), at=Location(10, 30), rotation=0)
    layout.place(Part("NT"), at=Beside(Part("RS"), Edge.NORTH, copper=True, align=(1, PadRef(Part("RS"), 1))),
                 rotation=0)
    plan = layout.resolve()
    assert not [f for f in plan.findings if "NT" in f or "RS" in f], plan.findings
    assert _gap(plan, ("NT", 2), ("RS", 1)) == pytest.approx(CLEARANCE, abs=1e-4)
    assert _pads(plan, "NT", 1)[0].box.center.x == pytest.approx(10.0, abs=1e-6)
    out = tmp_path / "out.kicad_pcb"
    apply_plan(str(pcb), plan, str(out))
    shutil.copy(pcb.with_suffix(".kicad_pro"), out.with_suffix(".kicad_pro"))      # the netclass clearance
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--output", str(report), str(out)],
                   capture_output=True, timeout=120)
    bad = [x for x in json.loads(report.read_text()).get("violations", [])
           if x.get("type") in ("clearance", "shorting_items", "courtyards_overlap", "copper_edge_clearance")]
    assert not bad, bad


def test_the_sweep_finds_the_last_contact_of_random_convex_pairs():
    """The standoff is the greatest translation at which two polygons are exactly `d` apart, checked against a
    fine scan."""
    import math
    import random
    from placemat.geometry import circle_polygon
    from placemat.placer import sweep_standoff
    rnd = random.Random(7)

    def shape():
        x, y = rnd.uniform(-1, 1), rnd.uniform(-1, 1)
        if rnd.random() < 0.5:
            return circle_polygon(Location(x, y), rnd.uniform(0.15, 0.6), 24)
        w, h, a = rnd.uniform(0.3, 1.5), rnd.uniform(0.3, 1.5), rnd.uniform(0, math.pi)
        c, s = math.cos(a), math.sin(a)
        return tuple((x + c * px - s * py, y + s * px + c * py)
                     for px, py in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)))

    for _ in range(60):
        a, b, d = shape(), shape(), rnd.choice((0.1, 0.2, 0.4))
        u = rnd.choice(((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)))
        t = sweep_standoff(a, b, u, d)
        near = [k / 1000.0 for k in range(-6000, 6001)
                if poly_distance(tuple((x + k / 1000.0 * u[0], y + k / 1000.0 * u[1]) for x, y in a), b) < d - 1e-9]
        if t is None:
            assert not near
        else:
            assert near and max(near) == pytest.approx(t, abs=2e-3)
