"""A track point on a pad's edge, touching it: PadRef(..., edge=, along=).
For a sense track that must meet its pad at one chosen edge (a shunt's
inner edge) and nowhere else."""
import pytest

from placemat.values import Along, Edge, Part, PadRef


def test_along_without_an_edge_is_refused():
    with pytest.raises(TypeError):
        PadRef(Part("r1"), 1, along=Along.END)


def test_an_edge_is_an_edge_and_along_is_an_along():
    with pytest.raises(TypeError):
        PadRef(Part("r1"), 1, edge="south")
    with pytest.raises(TypeError):
        PadRef(Part("r1"), 1, edge=Edge.SOUTH, along="end")


def test_a_plain_padref_digests_as_before():
    from placemat.reuse import canonical
    text = str(canonical(PadRef(Part("r1"), 1)))
    assert "edge" not in text and "along" not in text


def test_offset_and_local_keep_the_edge():
    p = PadRef(Part("r1"), 1, edge=Edge.SOUTH, along=Along.END)
    for q in (p.offset(0.1, 0.0), p.local(0.0, 0.1)):
        assert q.edge is Edge.SOUTH and q.along is Along.END


import dataclasses

from placemat.copper import Track
from placemat.geometry import circle_polygon
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Location, Net, Past
from tests.fixtures import board_geometry, footprint

F = CopperLayer.F
W, OVER = 0.2, 0.005          # the fixture's track width; how far a tap's copper overlaps its pad


def _board(round_pad=False, rotation=0.0):
    """R1 at (20, 20): pad 1 (net A) x 18.1 to 19.1, pad 2 (net B) x 20.9 to
    21.9, both y 19.5 to 20.5. `round_pad`: pad 1 a disc of radius 0.5."""
    r1 = footprint("R1", 20, 20, w=4, h=2, inst="r1", nets=("A", "B"))
    if round_pad:
        disc = circle_polygon(Location(18.6, 20.0), 0.5, 32)
        r1 = dataclasses.replace(r1, pads=(dataclasses.replace(r1.pads[0], outlines=(disc,), box=Box.of_points(disc)),
                                           r1.pads[1]))
    b = Board(board_geometry([r1], width=60, height=60), edge_margin=1.0)
    b.place(Part("r1"), at=Location(20, 20), rotation=rotation)
    return b


def _legs(plan):
    return [op for op in plan.copper if isinstance(op, Track)]


def _pad_box(plan, number):
    return next(s.box for s in plan.occupancy.items["R1"].shapes if s.label == str(number) and s.kind == "pad")


def test_a_tap_lies_against_its_edge_and_meets_the_pad_nowhere_else():
    b = _board()
    b.track(Net("A"), [PadRef(Part("r1"), 1, edge=Edge.EAST), Location(19.1 + W / 2 - OVER, 25)], layer=F, chamfer=0)
    plan = b.resolve()
    first = _legs(plan)[0]
    assert (first.start.x, first.start.y) == pytest.approx((19.1 + W / 2 - OVER, 20.0))
    assert min(x for leg in _legs(plan) for x, _ in leg.polygon) == pytest.approx(19.1 - OVER, abs=1e-6)


def test_a_tap_at_the_end_of_its_edge_is_flush_with_the_pads_side():
    b = _board()
    b.track(Net("A"), [PadRef(Part("r1"), 1, edge=Edge.SOUTH, along=Along.END), Location(19.0, 25)],
            layer=F, chamfer=0)
    plan = b.resolve()
    first = _legs(plan)[0]
    assert (first.start.x, first.start.y) == pytest.approx((19.1 - W / 2, 20.5 + W / 2 - OVER))
    assert max(x for x, _ in first.polygon) == pytest.approx(19.1, abs=1e-6)


def test_the_edge_is_the_board_frames_on_a_turned_part():
    b = _board(rotation=90)
    b.track(Net("A"), [PadRef(Part("r1"), 1, edge=Edge.SOUTH), Location(25, 0)], layer=F, chamfer=0)
    plan = b.resolve()
    box = _pad_box(plan, 1)
    first = _legs(plan)[0]
    assert (first.start.x, first.start.y) == pytest.approx((box.center.x, box.bottom + W / 2 - OVER))


def test_past_across_a_tap_lies_level_with_it():
    b = _board()
    tap = PadRef(Part("r1"), 1, edge=Edge.SOUTH, along=Along.END)
    b.track(Net("A"), [tap, Past([PadRef(Part("r1"), 1)], Edge.EAST, across=tap), Location(19.4, 25)],
            layer=F, chamfer=0)
    first = _legs(b.resolve())[0]
    assert first.start.y == pytest.approx(20.5 + W / 2 - OVER)
    assert first.end.y == pytest.approx(first.start.y) and first.end.x == pytest.approx(19.1 + 0.2 + W / 2)


def test_a_round_pad_is_tapped_at_the_middle_of_an_edge_and_not_at_its_end():
    b = _board(round_pad=True)
    b.track(Net("A"), [PadRef(Part("r1"), 1, edge=Edge.SOUTH), Location(18.6, 25)], layer=F, chamfer=0)
    first = _legs(b.resolve())[0]
    assert first.start.y == pytest.approx(20.5 + W / 2 - OVER)
    b = _board(round_pad=True)
    b.track(Net("A"), [PadRef(Part("r1"), 1, edge=Edge.SOUTH, along=Along.END), Location(18.6, 25)], layer=F)
    with pytest.raises(ValueError, match="R1"):
        b.resolve()


def test_a_tap_anywhere_but_a_track_point_or_pasts_across_is_refused():
    b = _board()
    b.via(Net("A"), PadRef(Part("r1"), 1, edge=Edge.EAST))
    with pytest.raises(ValueError, match="edge="):
        b.resolve()
    b = _board()
    with pytest.raises(TypeError, match="edge="):
        b.track(Net("A"), [PadRef(Part("r1"), 1), Past([PadRef(Part("r1"), 1, edge=Edge.EAST)], Edge.EAST),
                           Location(25, 25)], layer=F)


def _shunt_board():
    """An upright shunt RS at (30, 30): VSHUNT pad north, VPROT pad south,
    each 1.2 x 1.57, a 0.76 gap between them; a sense pad of each net, R5's
    north-east and U1's south-east. Each tap leaves the middle of its pad's
    inner edge, runs east in the gap, and turns to its sense pad."""
    from placemat.board_geometry import Footprint
    from placemat.values import Face
    from tests.fixtures import pad

    def part(ref, pads, cx, cy):
        body = Box.union([p.box for p in pads]).inflate(0.2)
        return Footprint(ref, ref.lower(), None, ref, Location(cx, cy), 0.0, Face.FRONT, body, body.inflate(0.1),
                         body, tuple(pads))
    rs = part("RS", [pad("RS", "rs", 1, "VSHUNT", 30, 28.835, 1.2, 1.57),
                     pad("RS", "rs", 2, "VPROT", 30, 31.165, 1.2, 1.57)], 30, 30)
    r5 = part("R5", [pad("R5", "r5", 1, "VSHUNT", 34, 26, 1.0, 1.0)], 34, 26)
    u1 = part("U1", [pad("U1", "u1", 1, "VPROT", 34, 34, 1.0, 1.0)], 34, 34)
    b = Board(board_geometry([rs, r5, u1], width=60, height=60), edge_margin=1.0)
    vs = PadRef(Part("rs"), 1, edge=Edge.SOUTH)
    vp = PadRef(Part("rs"), 2, edge=Edge.NORTH)
    lane = 30.6 + 0.2 + W / 2
    b.track(Net("VSHUNT"), [vs, Past([PadRef(Part("rs"), 1)], Edge.EAST, across=vs), Location(lane, 26),
                            PadRef(Part("r5"), 1)], layer=F, chamfer=0)
    b.track(Net("VPROT"), [vp, Past([PadRef(Part("rs"), 2)], Edge.EAST, across=vp), Location(lane, 34),
                           PadRef(Part("u1"), 1)], layer=F, chamfer=0)
    return b.resolve()


def test_a_shunts_taps_pass_kicads_drc_and_are_connected(tmp_path):
    """Both taps in the 0.76 mm gap: KiCad finds no clearance violation, no
    short, and nothing unconnected on either sense net."""
    import json
    import subprocess
    pcbnew = pytest.importorskip("pcbnew")
    plan = _shunt_board()
    board = pcbnew.CreateEmptyBoard()
    v = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
    nets = {}
    for name in ("VSHUNT", "VPROT"):
        nets[name] = pcbnew.NETINFO_ITEM(board, name)
        board.Add(nets[name])
    for ref, pads in (("RS", ((1, "VSHUNT", 30, 28.835, 1.2, 1.57), (2, "VPROT", 30, 31.165, 1.2, 1.57))),
                      ("R5", ((1, "VSHUNT", 34, 26, 1.0, 1.0),)), ("U1", ((1, "VPROT", 34, 34, 1.0, 1.0),))):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPosition(v(pads[0][2], pads[0][3]))
        board.Add(fp)
        for number, net, x, y, w, h in pads:
            p = pcbnew.PAD(fp)
            p.SetNumber(str(number))
            p.SetShape(pcbnew.PAD_SHAPE_RECT)
            p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            ls = pcbnew.LSET()
            ls.AddLayer(pcbnew.F_Cu)
            p.SetLayerSet(ls)
            p.SetSize(v(w, h))
            p.SetPosition(v(x, y))
            fp.Add(p)
            p.SetNet(nets[net])
    for t in (op for op in plan.copper if isinstance(op, Track)):
        tr = pcbnew.PCB_TRACK(board)
        tr.SetStart(v(t.start.x, t.start.y))
        tr.SetEnd(v(t.end.x, t.end.y))
        tr.SetWidth(pcbnew.FromMM(t.width))
        tr.SetLayer(pcbnew.F_Cu)
        tr.SetNet(nets[t.net])
        board.Add(tr)
    pcb = tmp_path / "shunt.kicad_pcb"
    board.Save(str(pcb))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    data = json.loads(report.read_text())
    bad = [x for x in data.get("violations", []) if x.get("type") in ("clearance", "shorting_items", "tracks_crossing")]
    assert not bad, bad
    assert not data.get("unconnected_items"), data.get("unconnected_items")
    assert len([op for op in plan.copper if isinstance(op, Track)]) >= 6
