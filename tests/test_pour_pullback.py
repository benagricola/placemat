"""A pour with swallow_pads pulls back from every other net's copper to the
netclass clearance, as a zone fill does, dropping any piece the pull-back
cuts off that touches no named or swallowed pad. Real case: a pour over a
clamp's pad and three capacitor ends came 0.15 mm from a 100 nF's other-net
pad against a 0.16 mm rule (kicad reported 3 clearance errors) - the pour's
own shape already ran that close, before any growing over same-net pads.

Built on a from-scratch synthetic board (as test_layers.py's _board_with
does) so the clearance and the pad positions are exact, not whatever a real
board's parts happen to leave."""
import pcbnew
import pytest

from placemat.geometry import point_in_polygon, poly_distance
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.values import Box, CopperLayer, Location, Net
from tests.conftest import needs_kicad

pytestmark = needs_kicad


def _vec(x, y):
    return pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6)))


def _add_pad(fp, number, net, x, y, w=1.0, h=1.0):
    pad = pcbnew.PAD(fp)
    pad.SetNumber(number)
    pad.SetShape(pcbnew.PAD_SHAPE_RECTANGLE)
    pad.SetSize(pcbnew.VECTOR2I(int(round(w * 1e6)), int(round(h * 1e6))))
    pad.SetPosition(_vec(x, y))
    pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
    pad.SetLayerSet(pcbnew.PAD.SMDMask())
    if net is not None:            # None: no net at all (GetNetCode() <= 0), same as a fiducial or a locating pad
        pad.SetNet(net)
    fp.Add(pad)
    return pad


def _board(tmp_path, pads, clearance=0.16):
    """A 40x40 board with one footprint U1 carrying `pads`
    (number, net_name, x, y, w, h), at the netclass clearance given."""
    b = pcbnew.CreateEmptyBoard()
    b.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(pcbnew.FromMM(clearance))
    for a, c in (((0, 0), (40, 0)), ((40, 0), (40, 40)), ((40, 40), (0, 40)), ((0, 40), (0, 0))):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(_vec(*a))
        s.SetEnd(_vec(*c))
        b.Add(s)
    nets = {}
    fp = pcbnew.FOOTPRINT(b)
    fp.SetReference("U1")
    fp.SetPosition(_vec(20, 20))
    b.Add(fp)
    for number, net_name, x, y, w, h in pads:
        if net_name is None:            # a pad with no net at all
            _add_pad(fp, number, None, x, y, w, h)
            continue
        if net_name not in nets:
            n = pcbnew.NETINFO_ITEM(b, net_name)
            b.Add(n)
            nets[net_name] = n
        _add_pad(fp, number, nets[net_name], x, y, w, h)
    path = tmp_path / "pullback.kicad_pcb"
    b.Save(str(path))
    return path


# pad 1, 2, 3 on PROBE_A in a row; pad 4 on PROBE_B 0.2 mm north of pad 1
_THREE_AND_A_NEIGHBOUR = [
    ("1", "PROBE_A", 10.0, 10.0, 1.0, 1.0),
    ("2", "PROBE_A", 12.0, 10.0, 1.0, 1.0),
    ("3", "PROBE_A", 14.0, 10.0, 1.0, 1.0),
    ("4", "PROBE_B", 10.0, 8.8, 1.0, 1.0),
]


def test_a_swallow_pour_keeps_the_clearance_from_a_foreign_pad_beside_it(tmp_path):
    pcb = _board(tmp_path, _THREE_AND_A_NEIGHBOUR, clearance=0.16)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    # a band across the row that runs right up near pad 4, as the real board did
    pts = [Location(9.0, 9.4), Location(15.0, 9.4), Location(15.0, 10.6), Location(9.0, 10.6)]
    b.pour(Net("PROBE_A"), pts, layer=CopperLayer.F, swallow_pads=True)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    u1 = after.footprint("U1")
    pad4 = u1.pad(4)
    polys = [c for c in after.copper if c.kind == "poly" and c.net == "PROBE_A"]
    assert polys
    gap = min(poly_distance(o, pad4.outlines[0]) for p in polys for o in p.outlines)
    assert gap >= 0.16 - 1e-6, gap
    # still covers the three pads it was declared over
    for number in (1, 2, 3):
        c = u1.pad(number).box.center
        assert any(point_in_polygon((c.x, c.y), o) for p in polys for o in p.outlines), number


def test_migration_a_pads_pour_over_a_row_keeps_clearance_from_a_foreign_pad(tmp_path):
    """docs/audits/2026-09-29-layout-scripts.md ("L197 `pour_box` over pins
    1-3 plus a via's width"): a `pour_box`-style pour, hand-built from the
    same-net pads' own union grown by a margin, run over a row with another
    net's pad close beside it. Rewritten as `board.pour(...,
    swallow_pads=True)`, the written pour must still cover the row and keep
    the netclass clearance from the foreign pad - measured on the written
    board, not the declared shape."""
    pcb = _board(tmp_path, _THREE_AND_A_NEIGHBOUR, clearance=0.16)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    # pour_box's own arithmetic: the row's own pads, boxed and grown by a via's width
    row = Box.union([Box(x - 0.5, y - 0.5, x + 0.5, y + 0.5) for _, net, x, y, _, _ in _THREE_AND_A_NEIGHBOUR
                     if net == "PROBE_A"])
    margin = 0.3
    box = row.inflate(margin)
    pts = [Location(box.left, box.top), Location(box.right, box.top),
          Location(box.right, box.bottom), Location(box.left, box.bottom)]
    b.pour(Net("PROBE_A"), pts, layer=CopperLayer.F, swallow_pads=True)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    u1 = after.footprint("U1")
    pad4 = u1.pad(4)
    polys = [c for c in after.copper if c.kind == "poly" and c.net == "PROBE_A"]
    assert polys
    gap = min(poly_distance(o, pad4.outlines[0]) for p in polys for o in p.outlines)
    assert gap >= 0.16 - 1e-6, gap
    for number in (1, 2, 3):
        c = u1.pad(number).box.center
        assert any(point_in_polygon((c.x, c.y), o) for p in polys for o in p.outlines), number


def test_a_pour_without_swallow_pads_keeps_its_given_shape_exactly(tmp_path):
    """Documented and unchanged: no pull-back at all without swallow_pads."""
    pcb = _board(tmp_path, _THREE_AND_A_NEIGHBOUR, clearance=0.16)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    pts = [Location(9.0, 9.4), Location(15.0, 9.4), Location(15.0, 10.6), Location(9.0, 10.6)]
    b.pour(Net("PROBE_A"), pts, layer=CopperLayer.F, swallow_pads=False, stroke=0.0)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    polys = [c for c in after.copper if c.kind == "poly" and c.net == "PROBE_A"]
    assert len(polys) == 1
    box = polys[0].box
    assert (round(box.left, 2), round(box.top, 2), round(box.right, 2), round(box.bottom, 2)) == (9.0, 9.4, 15.0, 10.6)


# pad 1 on PROBE_A; pad 4 a no-net pad (a fiducial, a locating pad, GetNetCode() <= 0) beside it
_ONE_AND_A_NO_NET_NEIGHBOUR = [
    ("1", "PROBE_A", 10.0, 10.0, 1.0, 1.0),
    ("4", None, 10.0, 8.8, 1.0, 1.0),
]


def test_existing_board_copper_is_one_of_the_pull_backs_obstacles(tmp_path):
    """Board copper not in plan.copper - a stamped cell's own track, carried
    whole by `_move_cell` rather than planned this run - is still one of
    the pull-back's obstacles.

    Exercised directly against `_existing_board_copper`/
    `_foreign_pour_obstacles` rather than through a full `apply_plan`
    round trip: a floating track with no pad of its own net anywhere near
    it is connectivity-orphaned, and KiCad's own `board.Save()` reassigns
    such a track's net when it saves - a pcbnew quirk with nothing to do
    with the pull-back this test targets."""
    from placemat.copper import Pour
    from placemat.kicad import write as W
    pads = [("1", "PROBE_A", 10.0, 10.0, 1.0, 1.0), ("2", "PROBE_B", 30.0, 30.0, 1.0, 1.0)]
    pcb = _board(tmp_path, pads, clearance=0.16)
    raw = pcbnew.LoadBoard(str(pcb))
    other = raw.FindNet("PROBE_B")
    t = pcbnew.PCB_TRACK(raw)
    t.SetLayer(pcbnew.F_Cu)
    t.SetWidth(pcbnew.FromMM(0.3))
    t.SetStart(_vec(9.0, 9.3))
    t.SetEnd(_vec(11.0, 9.3))
    t.SetNet(other)
    raw.Add(t)
    raw.Save(str(pcb))

    geometry = read_board(pcb)
    board = pcbnew.LoadBoard(str(pcb))
    existing = W._existing_board_copper(board, geometry)
    assert any(net == "PROBE_B" for _, net, _, _ in existing), existing

    op = Pour("PROBE_A", CopperLayer.F, ((9.0, 9.4), (11.0, 9.4), (11.0, 10.6), (9.0, 10.6)), stroke=0.2)
    obstacles = W._foreign_pour_obstacles(board, op, geometry, other_ops=(), existing=existing)
    # the far PROBE_B pad (near 30, 30) is an obstacle regardless; the track (near 9.0-11.0, 9.3) is
    # the one this fix adds
    near_track = [poly for poly, _ in obstacles if any(8.0 <= x <= 12.0 and 9.0 <= y <= 9.6 for x, y in poly)]
    assert near_track, obstacles


def test_a_swallow_pour_keeps_the_clearance_from_a_pad_with_no_net(tmp_path):
    """A pad with no net is still KiCad copper the pull-back must keep clear
    of, at the board's own default clearance (it names no netclass to look
    one up in)."""
    pcb = _board(tmp_path, _ONE_AND_A_NO_NET_NEIGHBOUR, clearance=0.16)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    pts = [Location(9.0, 9.4), Location(11.0, 9.4), Location(11.0, 10.6), Location(9.0, 10.6)]
    b.pour(Net("PROBE_A"), pts, layer=CopperLayer.F, swallow_pads=True)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    u1 = after.footprint("U1")
    no_net_pad = u1.pad(4)
    polys = [c for c in after.copper if c.kind == "poly" and c.net == "PROBE_A"]
    assert polys
    gap = min(poly_distance(o, no_net_pad.outlines[0]) for p in polys for o in p.outlines)
    assert gap >= b.geometry.default_clearance - 1e-6, gap


# pad 1, 2 on PROBE_A either side; pad 3 a tall PROBE_B pad between them, splitting the band in two
_TWO_AND_A_SPLITTER = [
    ("1", "PROBE_A", 10.0, 10.0, 1.0, 1.0),
    ("2", "PROBE_A", 16.0, 10.0, 1.0, 1.0),
    ("3", "PROBE_B", 13.0, 10.0, 1.0, 3.0),
]


def test_a_swallow_pour_keeps_every_piece_the_pull_back_splits_it_into(tmp_path):
    """A pull-back that cuts a pour into several separate outlines must keep
    every one once the board is saved and reloaded, not just the first: a
    `PCB_SHAPE` of kind `gr_poly` writes only one outline, so the writer
    must draw one `PCB_SHAPE` per surviving piece."""
    pcb = _board(tmp_path, _TWO_AND_A_SPLITTER, clearance=0.16)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    pts = [Location(9.0, 9.4), Location(17.0, 9.4), Location(17.0, 10.6), Location(9.0, 10.6)]
    b.pour(Net("PROBE_A"), pts, layer=CopperLayer.F, swallow_pads=True)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    u1 = after.footprint("U1")
    polys = [c for c in after.copper if c.kind == "poly" and c.net == "PROBE_A"]
    assert len(polys) >= 2, "the pull-back should have split the pour into two pieces"
    for number in (1, 2):
        c = u1.pad(number).box.center
        assert any(point_in_polygon((c.x, c.y), o) for p in polys for o in p.outlines), number


def test_a_named_pad_isolated_by_the_pull_back_is_a_finding(tmp_path):
    """A pour small enough that pulling back from a touching foreign pad
    cuts it off entirely: reported, not silently dropped."""
    pads = [
        ("1", "PROBE_A", 10.0, 10.0, 1.0, 1.0),
        ("4", "PROBE_B", 10.0, 10.0, 1.0, 1.0),      # right over pad 1: no room anywhere near it
    ]
    pcb = _board(tmp_path, pads, clearance=0.16)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    pts = [Location(9.45, 9.45), Location(10.55, 9.45), Location(10.55, 10.55), Location(9.45, 10.55)]
    b.pour(Net("PROBE_A"), pts, layer=CopperLayer.F, swallow_pads=True)
    plan = b.resolve()
    apply_plan(pcb, plan)
    assert any("joined to nothing" in f and "U1.1" in f for f in plan.findings), plan.findings


def test_two_swallow_pours_of_different_nets_keep_clearance_from_each_others_growth(tmp_path):
    """Two swallow pours of different nets, each over one pad of a small
    two-pad part 0.4 mm apart. Each grows round its own pad; the pull-back
    must keep the clearance from the other pour as written (grown round its
    pad), not only from its declared outline. Real case: two pours over the
    two ends of a small part met, which KiCad reported as shorting items."""
    pads = [("1", "PROBE_A", 10.0, 10.0, 0.5, 0.5), ("2", "PROBE_B", 10.9, 10.0, 0.5, 0.5)]
    pcb = _board(tmp_path, pads, clearance=0.2)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    b.pour(Net("PROBE_A"), [Location(7.0, 9.7), Location(10.1, 9.7), Location(10.1, 10.3), Location(7.0, 10.3)],
           layer=CopperLayer.F, swallow_pads=True)
    b.pour(Net("PROBE_B"), [Location(10.8, 9.7), Location(14.0, 9.7), Location(14.0, 10.3), Location(10.8, 10.3)],
           layer=CopperLayer.F, swallow_pads=True)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    a = [o for c in after.copper if c.kind == "poly" and c.net == "PROBE_A" for o in c.outlines]
    bb = [o for c in after.copper if c.kind == "poly" and c.net == "PROBE_B" for o in c.outlines]
    assert a and bb
    gap = min(poly_distance(p, q) for p in a for q in bb)
    assert gap >= 0.2 - 1e-6, gap
    u1 = after.footprint("U1")
    for number, outlines in ((1, a), (2, bb)):
        c = u1.pad(number).box.center
        assert any(point_in_polygon((c.x, c.y), o) for o in outlines), number


def test_a_pad_the_pull_back_cuts_short_of_its_centre_is_still_joined(tmp_path):
    """Two wide-stroked swallow pours over the two ends of a small part: each
    pull-back cuts the other's pad past its centre, but the pour's fill still
    overlaps its pad and its stroke covers the rest, so the pad is joined (as
    KiCad's connectivity says) and no finding names it."""
    pads = [("1", "PROBE_A", 10.0, 10.0, 0.5, 0.5), ("2", "PROBE_B", 10.9, 10.0, 0.5, 0.5)]
    pcb = _board(tmp_path, pads, clearance=0.2)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    b.pour(Net("PROBE_A"), [Location(7.0, 9.7), Location(10.1, 9.7), Location(10.1, 10.3), Location(7.0, 10.3)],
           layer=CopperLayer.F, stroke=0.5, swallow_pads=True)
    b.pour(Net("PROBE_B"), [Location(10.8, 9.7), Location(14.0, 9.7), Location(14.0, 10.3), Location(10.8, 10.3)],
           layer=CopperLayer.F, stroke=0.5, swallow_pads=True)
    plan = b.resolve()
    apply_plan(pcb, plan)
    assert not any("joined to nothing" in f for f in plan.findings), plan.findings
    after = read_board(pcb)
    u1 = after.footprint("U1")
    for number, net in ((1, "PROBE_A"), (2, "PROBE_B")):
        outlines = [o for c in after.copper if c.kind == "poly" and c.net == net for o in c.outlines]
        assert outlines, net
        assert min(poly_distance(o, u1.pad(number).outlines[0]) for o in outlines) == 0.0, net


def test_two_pours_on_adjacent_fine_pitch_pins_each_stay_joined_to_their_pin(tmp_path):
    """Two swallow pours of different nets over two neighbouring 0.2 mm pins
    0.3 mm apart, one pour running north and one south. Each pulls back from
    the other as KiCad's zone priority settles two fills: the one drawn
    first keeps its fill, the later one keeps clear of it as written - not
    both yielding over the same gap - so each keeps a strip over its own pin
    and runs on to its far end."""
    pads = [("1", "PROBE_A", 10.0, 10.0, 0.2, 0.6), ("2", "PROBE_B", 10.5, 10.0, 0.2, 0.6)]
    pcb = _board(tmp_path, pads, clearance=0.16)
    b = Board(read_board(pcb), edge_margin=0.5, keep_going=True)
    b.size(width=40.0, height=40.0)
    # each run as wide as its pin, as a neck over the pins would be
    b.pour(Net("PROBE_A"), [Location(9.9, 5.0), Location(10.1, 5.0), Location(10.1, 10.1), Location(9.9, 10.1)],
           layer=CopperLayer.F, stroke=0.25, swallow_pads=True)
    b.pour(Net("PROBE_B"), [Location(10.4, 9.9), Location(10.6, 9.9), Location(10.6, 15.0), Location(10.4, 15.0)],
           layer=CopperLayer.F, stroke=0.25, swallow_pads=True)
    plan = b.resolve()
    apply_plan(pcb, plan)
    assert not any("joined to nothing" in f for f in plan.findings), plan.findings
    after = read_board(pcb)
    u1 = after.footprint("U1")
    a = [o for c in after.copper if c.kind == "poly" and c.net == "PROBE_A" for o in c.outlines]
    bb = [o for c in after.copper if c.kind == "poly" and c.net == "PROBE_B" for o in c.outlines]
    assert a and bb
    assert min(poly_distance(p, q) for p in a for q in bb) >= 0.16 - 1e-6
    assert min(poly_distance(o, u1.pad(1).outlines[0]) for o in a) == 0.0
    assert min(poly_distance(o, u1.pad(2).outlines[0]) for o in bb) == 0.0
    # and each still runs out to its far end, one piece with its pin
    assert any(point_in_polygon((10.0, 6.0), o) for o in a), a
    assert any(point_in_polygon((10.5, 14.0), o) for o in bb), bb
