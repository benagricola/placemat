"""KiCad's net-tie rules judged where KiCad's DRC judges them.

A net tie's drawn copper (a filled polygon graphic) meets another footprint's
pad: KiCad's DRC lets it (DRC_ENGINE::EvalRules gives a net tie's graphic no
clearance to the nets of the group it overlaps), and where a pad meets a net
tie's pad it lets the collision inside a pad of the net
(DRC_ENGINE::IsNetTieExclusion) at the position of SHAPE::Collide, which is
ported in placemat.kicad_collide. Boards are built in pcbnew, written and read
back by placemat; kicad-cli's DRC is the oracle for the verdict, and pcbnew's
own SHAPE::Collide for the shapes and the position."""
import json
import random
import subprocess

import pytest

from tests.conftest import needs_kicad

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")

CLEARANCE = 0.16
CHECKED = ("clearance", "shorting_items")
DRC_EPSILON_NM = 500                        # BOARD_DESIGN_SETTINGS::GetDRCEpsilon, 0.0005 mm
SHAPES = {"rect": pcbnew.PAD_SHAPE_RECT, "roundrect": pcbnew.PAD_SHAPE_ROUNDRECT, "oval": pcbnew.PAD_SHAPE_OVAL,
          "circle": pcbnew.PAD_SHAPE_CIRCLE}


def _vec(x, y):
    return pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6)))


class _Board:
    """A 40 mm board with a capacitor C (pad 1 net V, pad 2 net G 3 mm west of it), a net tie NT (pad 1 net V,
    pad 2 net W 0.5 mm north of it, a 0.3 mm bar of F.Cu between the pad centres: the stock 0.3 mm tie) and,
    when asked, a track."""

    def __init__(self, tmp_path, name="tie"):
        self.path = tmp_path / ("%s.kicad_pcb" % name)
        self.board = pcbnew.CreateEmptyBoard()
        self.board.GetDesignSettings().m_NetSettings.GetDefaultNetclass().SetClearance(pcbnew.FromMM(CLEARANCE))
        self.nets = {}
        for a, c in (((0, 0), (40, 0)), ((40, 0), (40, 40)), ((40, 40), (0, 40)), ((0, 40), (0, 0))):
            s = pcbnew.PCB_SHAPE(self.board, pcbnew.SHAPE_T_SEGMENT)
            s.SetLayer(pcbnew.Edge_Cuts)
            s.SetWidth(100000)
            s.SetStart(_vec(*a))
            s.SetEnd(_vec(*c))
            self.board.Add(s)
        self.items = {}

    def net(self, name):
        if name not in self.nets:
            self.nets[name] = pcbnew.NETINFO_ITEM(self.board, name)
            self.board.Add(self.nets[name])
        return self.nets[name]

    def _pad(self, fp, number, net, x, y, shape, w, h):
        pad = pcbnew.PAD(fp)
        pad.SetNumber(number)
        pad.SetShape(shape)
        pad.SetSize(_vec(w, h))
        pad.SetPosition(_vec(x, y))
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetLayerSet(pcbnew.PAD.SMDMask())
        if shape == pcbnew.PAD_SHAPE_ROUNDRECT:
            pad.SetRoundRectRadiusRatio(0.25)
        pad.SetNet(self.net(net))
        fp.Add(pad)
        return pad

    def cap(self, x, y, shape="roundrect", w=1.0, h=1.45, angle=0.0):
        """C: pad 1 (V) centred at (x, y), the part turned `angle` degrees about it."""
        fp = pcbnew.FOOTPRINT(self.board)
        fp.SetReference("C")
        fp.SetPosition(_vec(x, y))
        self.board.Add(fp)
        h = w if shape == "circle" else h
        self.items["cap1"] = self._pad(fp, "1", "V", x, y, SHAPES[shape], w, h)
        self.items["cap2"] = self._pad(fp, "2", "G", x - 3.0, y, SHAPES[shape], w, h)
        if angle:
            fp.SetOrientationDegrees(angle)
        self.items["cap"] = fp
        self.half = (w / 2, h / 2)
        self.at = (x, y)
        return fp

    def tie(self, x, y, angle=0.0, net_tie=True, d=0.3, gap=0.5):
        """NT, its pad 1 at (x, y), turned `angle` degrees counter-clockwise about it."""
        fp = pcbnew.FOOTPRINT(self.board)
        fp.SetReference("NT")
        fp.SetPosition(_vec(x, y))
        self.board.Add(fp)
        self.items["tie1"] = self._pad(fp, "1", "V", x, y, pcbnew.PAD_SHAPE_CIRCLE, d, d)
        self.items["tie2"] = self._pad(fp, "2", "W", x, y - gap, pcbnew.PAD_SHAPE_CIRCLE, d, d)
        bar = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_POLY)
        bar.SetLayer(pcbnew.F_Cu)
        bar.SetFilled(True)
        bar.SetWidth(0)
        pts = pcbnew.VECTOR_VECTOR2I()
        for px, py in ((-d / 2, 0), (-d / 2, -gap), (d / 2, -gap), (d / 2, 0)):
            pts.append(_vec(x + px, y + py))
        bar.SetPolyPoints(pts)
        fp.Add(bar)
        self.items["bar"] = bar
        if net_tie:
            fp.AddNetTiePadGroup("1, 2")
        if angle:
            fp.SetOrientationDegrees(angle)
        self.items["tie"] = fp
        return fp

    def standing_out(self, side="north", angle=None, **kw):
        """The tie stands out from `side` of C's pad 1: its pad 1 against the edge, 0.005 mm over it, pad 2 further out."""
        out = {"north": (0, -1), "west": (-1, 0), "south": (0, 1), "east": (1, 0)}[side]
        turn = {"north": 0.0, "west": 90.0, "south": 180.0, "east": 270.0}[side]
        (hw, hh), (cx, cy) = self.half, self.at
        reach = (hh if out[0] == 0 else hw) - 0.15 + 0.005          # pad 1's centre, from the pad's centre
        return self.tie(cx + out[0] * reach, cy + out[1] * reach, turn if angle is None else angle, **kw)

    def track(self, net, a, b, width=0.16):
        t = pcbnew.PCB_TRACK(self.board)
        t.SetLayer(pcbnew.F_Cu)
        t.SetStart(_vec(*a))
        t.SetEnd(_vec(*b))
        t.SetWidth(int(round(width * 1e6)))
        t.SetNet(self.net(net))
        self.board.Add(t)
        return t

    def save(self, first=None):
        """Written. `first` "tie" or "cap" puts that footprint's items first in KiCad's DRC: it orders the pairs it
        tests by UUID (a pad and a graphic) or, in 10.0.6, by where the items were allocated, which is the file's
        order (two pads), so the pads, the bar and the footprints are given the lower UUIDs and written first."""
        names = {"tie": ("tie", "bar", "tie1", "tie2"), "cap": ("cap", "cap1", "cap2")}
        ids = {k: self.items[k].m_Uuid.AsString() for ks in names.values() for k in ks if k in self.items}
        self.board.Save(str(self.path))
        if first:
            text = self.path.read_text()
            second = "cap" if first == "tie" else "tie"
            for rank, group in enumerate((first, second)):
                for n, k in enumerate(names[group]):
                    if k in ids:
                        text = text.replace(ids[k], "%08x-0000-4000-8000-%012x" % (rank * 0x80000000 + 1, n))
            self.path.write_text(_footprints_in_order(text, first))
        return self.path


def _footprints_in_order(text, first):
    """`text`, a board file, with its two footprints written in the order that puts the one named `first` ("tie": NT,
    "cap": C) ahead."""
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if ln.startswith("\t(")] + [len(lines) - 1]
    blocks = [(lines[a:b], lines[a].startswith("\t(footprint")) for a, b in zip(starts, starts[1:])]
    feet = [blk for blk, is_fp in blocks if is_fp]
    want = "NT" if first == "tie" else "C"
    feet.sort(key=lambda blk: 0 if '(property "Reference" "%s"' % want in "\n".join(blk) else 1)
    out = lines[:starts[0]]
    it = iter(feet)
    for blk, is_fp in blocks:
        out += next(it) if is_fp else blk
    return "\n".join(out + lines[starts[-1]:])


def _drc(path):
    """The violations of kinds CHECKED kicad-cli reports on the board."""
    report = path.with_suffix(".json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(path)],
                   capture_output=True, timeout=120)
    return [v for v in json.loads(report.read_text()).get("violations", []) if v.get("type") in CHECKED]


def _occupancy(path):
    from placemat.kicad.read import read_board
    from placemat.occupancy import Occupancy
    from placemat.settings import Settings
    return Occupancy(read_board(str(path)), settings=Settings())


def _findings(path):
    """placemat's copper findings between the board's footprints, and its tracks, as it reads the written board."""
    occ = _occupancy(path)
    shapes = [s for item in occ.items.values() for s in item.shapes if s.kind in ("pad", "through", "copper")]
    shapes += [s for s in occ.copper if s.kind == "copper"]
    out = []
    for i, a in enumerate(shapes):
        for b in shapes[i + 1:]:
            if a.owner != b.owner:
                why = occ._conflict(a, b, None, exact=True)
                if why:
                    out.append(why)
    return out


# ------------------------------------------------------------------ the verdict: kicad-cli's DRC against placemat's
@pytest.mark.parametrize("shape,side", [("roundrect", "north"), ("roundrect", "west"), ("roundrect", "south"),
                                        ("roundrect", "east"), ("rect", "north"), ("oval", "north"),
                                        ("circle", "north"), ("circle", "east")])
def test_a_net_tie_standing_out_from_a_pad_of_its_net_is_not_a_conflict(tmp_path, shape, side):
    """The tie's bar is 0.145 mm from the pad it stands on, which pad 1 joins; KiCad gives the bar no clearance to
    the nets of the tie's pads."""
    b = _Board(tmp_path)
    b.cap(10, 10, shape)
    b.standing_out(side)
    path = b.save()
    assert _drc(path) == []
    assert _findings(path) == []


@pytest.mark.parametrize("first", ["tie", "cap"])
def test_the_verdict_does_not_depend_on_which_item_KiCads_DRC_tests_first(tmp_path, first):
    b = _Board(tmp_path)
    b.cap(10, 10)
    b.standing_out("north")
    path = b.save(first)
    assert _drc(path) == []
    assert _findings(path) == []


def test_the_same_tie_on_a_footprint_that_is_no_net_tie_is_a_conflict(tmp_path):
    b = _Board(tmp_path)
    b.cap(10, 10)
    b.standing_out("north", net_tie=False)
    path = b.save()
    assert _drc(path)
    assert [f for f in _findings(path) if "NT copper" in f]


def test_a_net_tie_lying_along_a_pad_edge_is_not_a_conflict(tmp_path):
    """Pad 1 over the north edge, the tie turned to lie along it, its pad 2 beyond the pad's east side: the bar
    overlaps the pad of its net along the edge."""
    b = _Board(tmp_path)
    b.cap(10, 10)
    b.tie(10.35, 10 - 0.725 - 0.15 + 0.005, angle=270.0)
    path = b.save()
    assert _drc(path) == []
    assert _findings(path) == []


def test_a_net_tie_against_a_pad_of_a_net_it_does_not_carry_is_a_conflict(tmp_path):
    b = _Board(tmp_path)
    b.cap(10, 10)
    b.tie(7.0, 10 - 0.725 - 0.15 + 0.005)                    # on pad 2, which is net G: neither V nor W
    path = b.save()
    assert _drc(path)
    assert _findings(path)


def test_a_track_of_a_net_tie_pads_net_across_the_bar_is_not_a_conflict(tmp_path):
    b = _Board(tmp_path)
    b.cap(10, 10)
    b.tie(20, 20)
    b.track("V", (20, 20), (20, 21))
    path = b.save()
    assert _drc(path) == []
    assert _findings(path) == []


def test_the_same_track_on_a_footprint_that_is_no_net_tie_is_a_conflict(tmp_path):
    b = _Board(tmp_path)
    b.cap(10, 10)
    b.tie(20, 20, net_tie=False)
    b.track("V", (20, 20), (20, 21))
    path = b.save()
    assert _drc(path)
    assert [f for f in _findings(path) if "NT copper" in f]


def test_the_exclusion_is_judged_either_way_round(tmp_path):
    b = _Board(tmp_path)
    b.cap(10, 10)
    b.standing_out("north")
    occ = _occupancy(b.save())
    bar = next(s for s in occ.items["NT"].shapes if s.kind == "copper")
    pad = next(s for s in occ.items["C"].shapes if s.label == "1")
    assert occ._conflict(bar, pad, None, exact=True) is None
    assert occ._net_tie_exclusion(bar, pad)
    assert occ._net_tie_exclusion(pad, bar)


# ------------------------------------------------------------------ the position: pcbnew's own SHAPE::Collide
def _kicad_collisions(path):
    """The collision of the bar and C's pad 1 as pcbnew's own effective shapes give it, each way round."""
    board = pcbnew.LoadBoard(str(path))
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    bar = next(g for g in fps["NT"].GraphicalItems() if g.GetLayerName() == "F.Cu")
    pad = next(p for p in fps["C"].Pads() if p.GetNumber() == "1")
    clr = int(CLEARANCE * 1e6) - DRC_EPSILON_NM
    out = []
    for a, b in ((bar.GetEffectiveShape(), pad.GetEffectiveShape(pcbnew.F_Cu)),
                 (pad.GetEffectiveShape(pcbnew.F_Cu), bar.GetEffectiveShape())):
        at = pcbnew.VECTOR2I(0, 0)
        out.append((a.Collide(b, clr, None, at), (at.x, at.y)))
    return out


def _placemat_collisions(path):
    """The same two collisions, of the shapes placemat reads, by the port."""
    from placemat import kicad_collide as kc
    occ = _occupancy(path)
    bar = next(s for s in occ.items["NT"].shapes if s.kind == "copper")
    pad = next(s for s in occ.items["C"].shapes if s.label == "1")
    cb, cp = occ._kicad_pair(bar, pad)
    clr = int(CLEARANCE * 1e6) - DRC_EPSILON_NM
    return [kc.collide(a, b, clr, first=True) for a, b in ((cb, cp), (cp, cb))]


@pytest.mark.parametrize("shape,side,angle", [("roundrect", "north", None), ("roundrect", "west", None),
                                              ("rect", "south", None), ("oval", "east", None),
                                              ("circle", "north", None), ("roundrect", "north", 45.0),
                                              ("rect", "north", 30.0), ("roundrect", "north", 180.0)])
def test_the_collision_position_is_where_KiCads_shapes_put_it(tmp_path, shape, side, angle):
    b = _Board(tmp_path)
    b.cap(10, 10, shape)
    b.standing_out(side, angle=angle)
    path = b.save()
    for (hit, at), ported in zip(_kicad_collisions(path), _placemat_collisions(path)):
        assert hit and ported is not None
        assert abs(ported[1][0] - at[0]) <= 1 and abs(ported[1][1] - at[1]) <= 1, (ported, at)


def test_the_collision_position_of_the_lying_tie_is_where_KiCads_shapes_put_it(tmp_path):
    b = _Board(tmp_path)
    b.cap(10, 10)
    b.tie(10.35, 10 - 0.725 - 0.15 + 0.005, angle=270.0)
    path = b.save()
    for (hit, at), ported in zip(_kicad_collisions(path), _placemat_collisions(path)):
        assert hit and ported is not None
        assert ported[1] == at, (ported, at)


def test_a_standing_out_collision_is_at_the_bars_end_in_pad_1():
    """A reported board's numbers (nm): the bar's end at pad 1's centre is 0.145 mm from the pad it stands on,
    and the corner the collision is placed at is 0.15 mm from pad 1's centre, which is inside it."""
    from placemat import kicad_collide as kc
    bar = kc.Compound([("p", ((-395000, 4245000), (-395000, 3745000), (-95000, 3745000), (-95000, 4245000)))])
    pad = kc.Compound([("r", -495000, 4640000, 500000, 950000), ("s", 5000, 4640000, -495000, 4640000, 500000),
                       ("s", -495000, 4640000, -495000, 5590000, 500000),
                       ("s", -495000, 5590000, 5000, 5590000, 500000), ("s", 5000, 5590000, 5000, 4640000, 500000)])
    tie_pad = kc.Compound([("c", -245000, 4245000, 150000)])
    for a, b in ((bar, pad), (pad, bar)):
        actual, at = kc.collide(a, b, 159500)
        assert (actual, at) == (145000, (-395000, 4245000))
        assert kc.collide_point(tie_pad, at, DRC_EPSILON_NM)


# ------------------------------------------------------------------ the shapes: placemat's port against pcbnew's
def _build(sh):
    v = pcbnew.VECTOR2I
    if sh[0] == "c":
        return pcbnew.SHAPE_CIRCLE(v(sh[1], sh[2]), sh[3])
    if sh[0] == "s":
        return pcbnew.SHAPE_SEGMENT(v(sh[1], sh[2]), v(sh[3], sh[4]), sh[5])
    if sh[0] == "r":
        return pcbnew.SHAPE_RECT(sh[1], sh[2], sh[3], sh[4])
    poly = pcbnew.SHAPE_SIMPLE()
    for x, y in sh[1]:
        poly.Append(x, y)
    return poly


def _compound(shapes):
    c = pcbnew.SHAPE_COMPOUND()
    for sh in shapes:
        e = _build(sh)
        e.thisown = 0                       # AddShape takes it
        c.AddShape(e)
    return c


def _random_shape(rnd, kind):
    span = 2_000_000
    pt = lambda: (rnd.randint(-span, span), rnd.randint(-span, span))
    if kind == "c":
        x, y = pt()
        return ("c", x, y, rnd.randint(50_000, 700_000))
    if kind == "s":
        a, b = pt(), pt()
        if rnd.random() < 0.3:
            b = (a[0] + rnd.choice([-1, 1]) * rnd.randint(0, span), a[1])
        return ("s", a[0], a[1], b[0], b[1], rnd.randint(0, 600_000))
    if kind == "r":
        x, y = pt()
        return ("r", x, y, rnd.randint(10_000, span), rnd.randint(10_000, span))
    if rnd.random() < 0.5:
        x, y = pt()
        w, h = rnd.randint(10_000, span), rnd.randint(10_000, span)
        return ("p", ((x, y), (x + w, y), (x + w, y + h), (x, y + h)))
    pts = [pt() for _ in range(3)]
    (ax, ay), (bx, by), (cx, cy) = pts
    if (bx - ax) * (cy - ay) - (by - ay) * (cx - ax) == 0:
        pts[2] = (cx + 1000, cy + 777)
    return ("p", tuple(pts))


def test_the_ported_collisions_agree_with_pcbnews_on_every_pair_of_shapes():
    """Random shapes - circles, segments with a width, square-cornered rectangles, polygons - two at a time, each
    in a compound as KiCad's effective shapes are: the same collisions at the same positions."""
    from placemat.kicad_collide import Compound, collide
    rnd = random.Random(11)
    hits = 0
    for ka in "csrp":
        for kb in "csrp":
            for _ in range(80):
                a, b = _random_shape(rnd, ka), _random_shape(rnd, kb)
                clr = rnd.choice([0, 50_000, 160_000, 500_000])
                at = pcbnew.VECTOR2I(0, 0)
                kicad = _compound([a]).Collide(_compound([b]), clr, None, at)
                mine = collide(Compound([a]), Compound([b]), clr, first=True)
                assert (mine is not None) == kicad, (a, b, clr)
                if kicad:
                    hits += 1
                    assert mine[1] == (at.x, at.y), (a, b, clr, mine, (at.x, at.y))
    assert hits > 100


def test_the_ported_collisions_agree_with_pcbnews_on_compounds():
    from placemat.kicad_collide import Compound, collide
    rnd = random.Random(12)
    for _ in range(400):
        a = [_random_shape(rnd, rnd.choice("csrp")) for _ in range(rnd.randint(1, 4))]
        b = [_random_shape(rnd, rnd.choice("csrp")) for _ in range(rnd.randint(1, 5))]
        clr = rnd.choice([0, 50_000, 160_000, 500_000])
        at = pcbnew.VECTOR2I(0, 0)
        kicad = _compound(a).Collide(_compound(b), clr, None, at)
        mine = collide(Compound(a), Compound(b), clr, first=True)
        assert (mine is not None) == kicad, (a, b, clr)
        if kicad:
            assert mine[1] == (at.x, at.y), (a, b, clr, mine, (at.x, at.y))


def test_the_ported_point_collision_agrees_with_pcbnews():
    """IsNetTieExclusion's test: an effective shape colliding with a point within the DRC epsilon."""
    from placemat.kicad_collide import Compound, collide_point
    rnd = random.Random(13)
    for _ in range(400):
        shapes = [_random_shape(rnd, rnd.choice("csrp")) for _ in range(rnd.randint(1, 4))]
        p = (rnd.randint(-2_000_000, 2_000_000), rnd.randint(-2_000_000, 2_000_000))
        point = pcbnew.VECTOR2I(*p)
        kicad = _compound(shapes).Collide(pcbnew.SEG(point, point), DRC_EPSILON_NM)     # how a point collides
        assert collide_point(Compound(shapes), p, DRC_EPSILON_NM) == kicad, (shapes, p)


def _flat(shape):
    out = []
    for v in (shape[1:5] if shape[0] == "r" else shape[1:]):         # a pad's rectangle also says how it was turned
        if isinstance(v, tuple):
            out += [c for p in v for c in p] if isinstance(v[0], tuple) else list(v)
        else:
            out.append(v)
    return out


@pytest.mark.parametrize("shape", ["rect", "roundrect", "oval", "circle"])
@pytest.mark.parametrize("read", [0.0, 90.0, 270.0])
@pytest.mark.parametrize("pose", [(0.0, 0.0, 0.0), (7.5, -3.25, 90.0), (-2.0, 4.0, 180.0), (3.0, 3.0, 30.0),
                                  (1.0, 2.0, 135.0)])
def test_a_pad_moved_and_turned_is_the_shape_KiCad_makes_of_it_there(tmp_path, shape, read, pose):
    """The pad as placemat holds it after a move (the shape it read, carried by the move that carries its outline)
    is within 2 nm of the shape pcbnew builds for the part standing there, outline starting at the same corner."""
    from placemat.geometry import Transform, transform_polygon
    from placemat.occupancy import Shape
    dx, dy, turn = pose
    here = _Board(tmp_path, "here")
    here.cap(10, 10, shape, angle=read)
    occ = _occupancy(here.save())
    pad = next(s for s in occ.items["C"].shapes if s.label == "1")
    t = Transform.translate(-10, -10).then(Transform.rotate(turn)).then(Transform.translate(10 + dx, 10 + dy))
    poly = transform_polygon(pad.poly, t, clean=False)
    moved = Shape(pad.owner, pad.kind, pad.faces, pad.layers, pad.net, poly, pad.box, pad.label)
    ported = occ._kicad_prims(moved, poly)
    there = _Board(tmp_path, "there")
    there.cap(10 + dx, 10 + dy, shape, angle=read + turn)
    from placemat.kicad.read import kicad_shapes
    want = kicad_shapes(there.items["cap1"].GetEffectiveShape(pcbnew.F_Cu))
    assert [s[0] for s in ported] == [s[0] for s in want]
    for a, b in zip(ported, want):
        assert len(_flat(a)) == len(_flat(b)) and max(abs(x - y) for x, y in zip(_flat(a), _flat(b))) <= 2, (a, b)


# ------------------------------------------------------------------ a part searched for, with a net tie riding it
def _riding_plan(path, rotation):
    from placemat.kicad.read import read_board
    from placemat.layout import Board
    from placemat.values import Along, Edge, PadRef, Part, Pin
    board = Board(read_board(str(path)), edge_margin=0.5, keep_going=True)
    board.size(width=40.0, height=40.0)
    board.place(Part("C"))
    board.place(Part("NT"), at=Pin(1, PadRef(Part("C"), 1, edge=Edge.NORTH, along=Along.MID)), rotation=rotation)
    return board.resolve()


@pytest.mark.parametrize("shape", ["roundrect", "rect", "circle"])
def test_a_datum_part_is_placed_with_a_net_tie_standing_out_from_its_pad(tmp_path, shape):
    """The part's search judges its rider before it commits either: the tie's bar against the pad it stands on,
    where the pad is read from KiCad as the compound KiCad collides."""
    b = _Board(tmp_path)
    b.cap(10, 10, shape)
    b.standing_out("north")
    plan = _riding_plan(b.save(), 0.0)
    assert not [f for f in plan.findings if "rider" in f or "no place" in f or "cannot be laid out" in f], plan.findings
    cap = next(s for s in plan.occupancy.items["C"].shapes if s.label == "1")
    tie = next(s for s in plan.occupancy.items["NT"].shapes if s.label == "1")
    assert tie.box.bottom == pytest.approx(cap.box.top + 0.005, abs=1e-6)


def test_the_same_riding_part_that_is_no_net_tie_is_refused(tmp_path):
    b = _Board(tmp_path)
    b.cap(10, 10)
    b.standing_out("north", net_tie=False)
    plan = _riding_plan(b.save(), 0.0)
    assert [f for f in plan.findings if "cannot be laid out with its riders" in f], plan.findings
