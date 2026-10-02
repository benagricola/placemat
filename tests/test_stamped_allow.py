"""A keepout's `allow=` nets reach KiCad and the board that stamps the cell. A rule area has no list of nets,
so the area is written allowing what the nets keep (tracks, vias, pads), a custom rule forbids it to every
other net, and the declaration rides in the zone name - which survives the module's save and pcb's stamp."""
import json
import subprocess

from placemat.board_geometry import allow_marker, split_allow, split_marker, stamped_net
from placemat.rules import AllowRule
from placemat.values import CopperLayer
from tests.conftest import needs_kicad

F, IN1, IN2, B = CopperLayer.F, CopperLayer.IN1, CopperLayer.IN2, CopperLayer.B


def test_the_marker_round_trips_nets_and_types_through_pcbs_stamp():
    name = "keepout antenna [*.Cu]" + allow_marker({"GND", "SIG_A"}, ("tracks", "vias")) + "_1"
    assert split_allow(name) == (("GND", "SIG_A"), ("tracks", "vias"))
    assert split_marker(name) == ("keepout antenna", "*")
    assert split_marker("keepout antenna" + allow_marker({"GND"}, ("vias",)) + "_1") == ("keepout antenna", None)


def test_a_net_name_with_the_markers_own_characters_survives():
    nets = {"A,B", "N|1", "X}", "Y]", "100%"}
    assert set(split_allow("keepout k" + allow_marker(nets, ("vias",)))[0]) == nets


def test_a_name_with_no_marker_declares_no_allow():
    assert split_allow("keepout vent_1") == ((), ())


def test_a_fragments_net_is_the_stamped_boards_most_particular_one():
    nets = {"GND", "sheet.FEED", "sheet.cell.SIG_A"}
    assert stamped_net("SIG_A", "sheet.cell", nets) == "sheet.cell.SIG_A"
    assert stamped_net("FEED", "sheet.cell", nets) == "sheet.FEED"
    assert stamped_net("GND", "sheet.cell", nets) == "GND"
    assert stamped_net("NOPE", "sheet.cell", nets) is None
    assert stamped_net("GND", None, nets) == "GND"


def test_the_rule_forbids_the_types_to_every_net_but_the_allowed():
    text = AllowRule("keepout antenna [*.Cu] {allow GND | tracks,vias}_1", ("GND", "X"), ("tracks", "vias")).text()
    assert "(constraint disallow track via)" in text
    assert "A.intersectsArea('keepout antenna [*.Cu] {allow GND | tracks,vias}_1')" in text
    assert "A.NetName != 'GND' && A.NetName != 'X'" in text
    assert text.startswith('(rule "keepout antenna allows GND, X"')


def test_a_rule_that_allows_no_net_forbids_the_types_to_all():
    text = AllowRule("keepout k_1", (), ("vias",)).text()
    assert "NetName" not in text and "(constraint disallow via)" in text


def _plan(allow, excludes=("fill", "tracks", "vias", "pads"), layers=(IN1, B)):
    from placemat.cutouts import Circle
    from placemat.layout import Board
    from placemat.values import Location, Net
    from tests.fixtures import board_geometry
    b = Board(board_geometry([], width=40, height=40, extra_nets=("GND", "SIG")), edge_margin=0.0)
    b.keepout(Circle(10.0), "antenna", at=Location(20, 20), layers=layers, excludes=excludes,
              allow=tuple(Net(n) for n in allow), why="the antenna's clearance")
    return b.resolve()


@needs_kicad
def test_a_keepout_that_allows_a_net_is_written_allowing_what_the_net_keeps_and_named_for_it(tmp_path):
    import pcbnew
    from placemat.kicad.write import _draw_keepouts
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(4)
    _draw_keepouts(board, _plan(["GND"]))
    (z,) = [z for z in board.Zones() if z.GetIsRuleArea()]
    assert z.GetZoneName() == "keepout antenna {allow GND | tracks,vias,pads}"
    assert not (z.GetDoNotAllowTracks() or z.GetDoNotAllowVias() or z.GetDoNotAllowPads())
    assert z.GetDoNotAllowZoneFills()                      # the net's copper may run through; the pour may not


@needs_kicad
def test_a_keepout_that_allows_no_net_is_written_as_it_always_was(tmp_path):
    import pcbnew
    from placemat.kicad.write import _draw_keepouts, allow_rules
    board = pcbnew.CreateEmptyBoard()
    plan = _plan([])
    _draw_keepouts(board, plan)
    (z,) = [z for z in board.Zones() if z.GetIsRuleArea()]
    assert z.GetZoneName().startswith("keepout antenna") and "{" not in z.GetZoneName()
    assert z.GetDoNotAllowVias() and z.GetDoNotAllowTracks() and z.GetDoNotAllowPads()
    assert allow_rules(plan, (F, B)) == []


def _drc(pcb):
    out = pcb.with_suffix(".json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(out), str(pcb)],
                   capture_output=True, timeout=120)
    return json.loads(out.read_text())["violations"]


def _copper(board, spec):
    """spec: ("via", x, y, net) | ("track", x0, y0, x1, y1, layer, net) | ("pad", x, y, net)."""
    import pcbnew
    mm = pcbnew.FromMM
    nets = {str(k): v for k, v in board.GetNetsByName().items()}

    def net(n):
        n = str(n)
        if nets.get(n) is None:
            nets[n] = pcbnew.NETINFO_ITEM(board, n)
            board.Add(nets[n])
        return nets[n]
    for kind, *a in spec:
        if kind == "via":
            x, y, n = a
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
            v.SetWidth(mm(0.6))
            v.SetDrill(mm(0.3))
            v.SetNet(net(n))
            board.Add(v)
        elif kind == "track":
            x0, y0, x1, y1, layer, n = a
            t = pcbnew.PCB_TRACK(board)
            t.SetLayer(layer)
            t.SetWidth(mm(0.2))
            t.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
            t.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
            t.SetNet(net(n))
            board.Add(t)
        else:
            x, y, n = a
            fp = pcbnew.FOOTPRINT(board)
            fp.SetReference("P%d" % len(board.GetFootprints()))
            fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
            p = pcbnew.PAD(fp)
            p.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            p.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
            p.SetSize(pcbnew.VECTOR2I(mm(0.9), mm(0.9)))
            p.SetDrillSize(pcbnew.VECTOR2I(mm(0.5), mm(0.5)))
            p.SetLayerSet(pcbnew.LSET.AllCuMask())
            p.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
            p.SetNumber("1")
            p.SetNet(net(n))
            fp.Add(p)
            board.Add(fp)


def _kicad_run(tmp_path, plan, with_rules=True):
    import pcbnew
    from placemat.kicad.write import _draw_keepouts, allow_rules
    from placemat.rules import write_rules
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(4)
    _draw_keepouts(board, plan)
    _copper(board, [("via", 18, 20, "GND"), ("via", 22, 20, "SIG"),
                    ("track", 17, 18, 19, 18, pcbnew.In1_Cu, "GND"), ("track", 21, 18, 23, 18, pcbnew.In1_Cu, "SIG"),
                    ("pad", 18, 22, "GND"), ("pad", 22, 22, "SIG"),
                    ("via", 36, 36, "SIG")])                              # outside the region
    pcb = tmp_path / "layout.kicad_pcb"
    board.Save(str(pcb))
    if with_rules:
        write_rules(str(pcb), allow_rules(plan, (F, IN1, IN2, B)))
    return [(v["type"], [i["description"] for i in v["items"]]) for v in _drc(pcb) if v["type"] == "items_not_allowed"]


@needs_kicad
def test_kicad_passes_the_allowed_nets_copper_and_flags_every_other_nets(tmp_path):
    found = _kicad_run(tmp_path, _plan(["GND"]))
    flagged = " ".join(d for _, items in found for d in items)
    assert "Via [SIG] on" in flagged and "Track [SIG]" in flagged and "[SIG]" in flagged
    assert "[GND]" not in flagged                                       # the via, track and pad on GND stand
    assert len(found) == 3, found                                       # SIG's via, track and pad; the one outside is nobody's


@needs_kicad
def test_without_the_rule_the_area_would_let_every_net_in(tmp_path):
    assert _kicad_run(tmp_path, _plan(["GND"]), with_rules=False) == []


@needs_kicad
def test_an_area_that_allows_nothing_still_flags_the_nets_copper(tmp_path):
    found = _kicad_run(tmp_path, _plan([]), with_rules=False)
    assert "[GND]" in " ".join(d for _, items in found for d in items)


def _stamped(tmp_path, name, nets=("GND", "sheet.cell.SIG_A")):
    """A board of the shape pcb layout makes of a stamped fragment: a rule area inside a cell's group."""
    import pcbnew
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(4)
    g = pcbnew.PCB_GROUP(b)
    g.SetName("sheet.cell")
    b.Add(g)
    z = pcbnew.ZONE(b)
    z.SetIsRuleArea(True)
    ls = pcbnew.LSET()
    ls.AddLayer(pcbnew.In1_Cu)
    ls.AddLayer(pcbnew.B_Cu)
    z.SetLayerSet(ls)
    z.SetDoNotAllowFootprints(False)
    z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowTracks(False)               # as the module wrote it: allowed, the rule forbids
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowPads(False)
    o = z.Outline()
    o.NewOutline()
    for px, py in ((10, 10), (30, 10), (30, 30), (10, 30)):
        o.Append(pcbnew.FromMM(px), pcbnew.FromMM(py))
    z.SetZoneName(name)
    b.Add(z)
    g.AddItem(z)
    _copper(b, [("via", 1, 1 + i, n) for i, n in enumerate(nets)])      # a net the board saves is one that is used
    path = tmp_path / "layout.kicad_pcb"
    b.Save(str(path))
    return path


NAME = "keepout antenna [*.Cu]" + allow_marker({"GND", "SIG_A"}, ("tracks", "vias", "pads")) + "_1"


@needs_kicad
def test_a_stamped_region_reads_with_the_nets_it_lets_through_as_the_board_names_them(tmp_path):
    from placemat.kicad.read import read_board
    (ra,) = read_board(_stamped(tmp_path, NAME)).rule_areas
    assert ra.allow == frozenset(("GND", "sheet.cell.SIG_A"))
    assert ra.relaxed == ("tracks", "vias", "pads")
    assert ra.excludes >= {"fill", "tracks", "vias", "pads"}          # it still forbids them to the rest
    assert ra.base == "keepout antenna" and ra.layers == frozenset((F, IN1, IN2, B))


@needs_kicad
def test_a_stamped_region_without_the_marker_reads_as_it_always_did(tmp_path):
    from placemat.kicad.read import read_board
    (ra,) = read_board(_stamped(tmp_path, "keepout antenna [*.Cu]_1")).rule_areas
    assert ra.allow == frozenset() and ra.relaxed == ()


@needs_kicad
def test_the_board_that_stamps_the_cell_writes_the_rule_the_module_did(tmp_path):
    """The parent's .kicad_dru carries the stamped region's rule, over the parent's own net names, and
    kicad-cli passes the allowed nets' vias in the cell and flags the others."""
    import pcbnew
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    from placemat.layout import Board
    pcb = _stamped(tmp_path, NAME)
    board = pcbnew.LoadBoard(str(pcb))
    _copper(board, [("via", 18, 20, "GND"), ("via", 22, 20, "sheet.cell.SIG_A"), ("via", 25, 25, "X")])
    board.Save(str(pcb))
    (tmp_path / "layout.kicad_pro").write_text("{}")
    plan = Board(read_board(pcb), edge_margin=0.0, keep_going=True).resolve()
    apply_plan(pcb, plan)
    dru = (tmp_path / "layout.kicad_dru").read_text()
    assert "A.NetName != 'GND' && A.NetName != 'sheet.cell.SIG_A'" in dru
    assert "(constraint disallow track via pad)" in dru
    found = [i["description"] for v in _drc(pcb) if v["type"] == "items_not_allowed" for i in v["items"]]
    assert len(found) == 1 and "[X]" in found[0], found
