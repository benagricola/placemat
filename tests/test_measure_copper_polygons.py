"""measure --copper lists a board's graphic copper polygons: net, layer, stroke,
filled, vertices, and per edge the nearest copper of another net, the gap from
the polygon's copper (its outline grown by half its stroke), the clearance the
pair needs and `under` where the gap is less. Boards are built in pcbnew;
kicad-cli's DRC is the oracle for the gaps."""
import json
import re
import subprocess

import pytest

from tests.conftest import needs_kicad

pytestmark = needs_kicad

pcbnew = pytest.importorskip("pcbnew")

STROKE = 0.2
CLEARANCE = 0.2


def _vec(x, y):
    return pcbnew.VECTOR2I(int(round(x * 1e6)), int(round(y * 1e6)))


class _Board:
    def __init__(self):
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

    def net(self, name):
        if name not in self.nets:
            self.nets[name] = pcbnew.NETINFO_ITEM(self.board, name)
            self.board.Add(self.nets[name])
        return self.nets[name]

    def polygon(self, net, pts, filled):
        s = pcbnew.PCB_SHAPE(self.board, pcbnew.SHAPE_T_POLY)
        s.SetLayer(pcbnew.F_Cu)
        s.SetFilled(filled)
        s.SetWidth(pcbnew.FromMM(STROKE))
        v = pcbnew.VECTOR_VECTOR2I()
        for p in pts:
            v.append(_vec(*p))
        s.SetPolyPoints(v)
        s.SetNet(self.net(net))
        self.board.Add(s)

    def pad(self, net, x0, y0, x1, y1):
        fp = pcbnew.FOOTPRINT(self.board)
        fp.SetReference("J%d" % len(self.board.GetFootprints()))
        fp.SetPosition(_vec((x0 + x1) / 2, (y0 + y1) / 2))
        self.board.Add(fp)
        p = pcbnew.PAD(fp)
        p.SetNumber("1")
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetSize(_vec(x1 - x0, y1 - y0))
        p.SetPosition(_vec((x0 + x1) / 2, (y0 + y1) / 2))
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetLayerSet(pcbnew.PAD.SMDMask())
        p.SetNet(self.net(net))
        fp.Add(p)

    def track(self, net, a, b, width=0.2):
        t = pcbnew.PCB_TRACK(self.board)
        t.SetLayer(pcbnew.F_Cu)
        t.SetStart(_vec(*a))
        t.SetEnd(_vec(*b))
        t.SetWidth(pcbnew.FromMM(width))
        t.SetNet(self.net(net))
        self.board.Add(t)

    def via(self, net, at, size=0.6, drill=0.3):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(_vec(*at))
        v.SetWidth(pcbnew.FromMM(size))
        v.SetDrill(pcbnew.FromMM(drill))
        v.SetNet(self.net(net))
        self.board.Add(v)


@pytest.fixture
def pcb(tmp_path):
    """FILL (filled, net A) (10, 10)-(14, 14): its east edge 0.35 from a pad, its north edge 0.1 from a track, its
    south edge 0.5 from a via. OUTL (unfilled, net B) (25, 10)-(29, 14): its east edge 0.1 from a pad, its north edge
    0.4 from a track, its south edge 0.3 from a via. Gaps are from the stroke's outer side."""
    b = _Board()
    b.polygon("A", [(10, 10), (14, 10), (14, 14), (10, 14)], True)
    b.pad("P", 14.1 + 0.35, 11, 16, 13)
    b.track("T", (11, 9.9 - 0.1 - 0.1), (13, 9.9 - 0.1 - 0.1))         # copper to y 9.9; the track's lower side 9.8
    b.via("V", (12, 14.1 + 0.5 + 0.3), 0.6)
    b.polygon("B", [(25, 10), (29, 10), (29, 14), (25, 14)], False)
    b.pad("Q", 29.1 + 0.1, 11, 31, 13)
    b.track("T", (26, 9.9 - 0.4 - 0.1), (28, 9.9 - 0.4 - 0.1))
    b.via("V", (27, 14.1 + 0.3 + 0.3), 0.6)
    path = tmp_path / "poly.kicad_pcb"
    b.board.Save(str(path))
    return path


def _measure(pcb, capsys, *nets):
    from placemat.cli import main
    assert main(["measure", str(pcb), "--copper", *nets, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def _polys(doc):
    return {p["net"]: p for p in doc["polygons"]}


def test_each_polygon_is_listed_with_its_stroke_fill_and_vertices(pcb, capsys):
    polys = _polys(_measure(pcb, capsys, "A", "B"))
    assert set(polys) == {"A", "B"}
    a, b = polys["A"], polys["B"]
    assert a["layer"] == b["layer"] == "F.Cu"
    assert a["width"] == pytest.approx(0.2) and a["filled"] is True and b["filled"] is False
    assert a["vertices"] == [[10, 10], [14, 10], [14, 14], [10, 14]]
    assert len(a["edges"]) == 4


def test_each_edge_names_its_nearest_foreign_copper_and_the_gap(pcb, capsys):
    polys = _polys(_measure(pcb, capsys, "A", "B"))
    for net, (east, north, south) in (("A", ((0.35, False), (0.1, True), (0.5, False))),
                                      ("B", ((0.1, True), (0.4, False), (0.3, False)))):
        poly = polys[net]
        v = poly["vertices"]
        edges = {e["start"] and (tuple(e["start"]), tuple(e["end"])): e for e in poly["edges"]}
        for (a, b), kind, (gap, under) in (((v[1], v[2]), "pad", east), ((v[0], v[1]), "track", north),
                                           ((v[2], v[3]), "via", south)):
            e = edges[(tuple(a), tuple(b))]
            assert e["nearest"]["kind"] == kind, (net, a, b, e)
            assert e["gap"] == pytest.approx(gap, abs=1e-4), (net, a, b, e)
            assert e["clearance"] == pytest.approx(CLEARANCE)
            assert e["under"] is under
    assert polys["A"]["edges"][0]["nearest"]["net"] == "T"


def test_the_gaps_agree_with_kicad_cli_drc_for_the_violating_edges(pcb, capsys, tmp_path):
    out = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(out), str(pcb)],
                   capture_output=True, timeout=120)
    actual = sorted(float(re.search(r"actual ([\d.]+) mm", v["description"]).group(1))
                    for v in json.loads(out.read_text())["violations"] if v["type"] == "clearance")
    under = sorted(e["gap"] for p in _measure(pcb, capsys, "A", "B")["polygons"] for e in p["edges"] if e["under"])
    assert len(actual) == len(under) == 2, (actual, under)
    assert under == pytest.approx(actual, abs=1e-3)


def test_the_text_form_prints_a_line_per_polygon_and_per_edge(pcb, capsys):
    from placemat.cli import main
    assert main(["measure", str(pcb), "--copper", "A"]) == 0
    lines = capsys.readouterr().out.splitlines()
    poly = [l for l in lines if "polygon" in l]
    assert len(poly) == 1 and "filled" in poly[0] and "A" in poly[0]
    edges = [l for l in lines if "edge (" in l]
    assert len(edges) == 4
    under = [l for l in edges if "under" in l]
    assert len(under) == 1 and "track T" in under[0]


def test_a_board_without_polygons_lists_none(tmp_path, capsys):
    b = _Board()
    b.track("T", (5, 5), (10, 5))
    path = tmp_path / "plain.kicad_pcb"
    b.board.Save(str(path))
    assert _measure(path, capsys)["polygons"] == []
