"""A keepout that admits parts by name or height is written as a KiCad rule
area that allows footprints, and a .kicad_dru rule forbids only the parts
it does not admit: KiCad cannot say the allow list or a height, and a part
placed by hand in the region should not be a DRC error when placemat
admits it."""
from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint

pytestmark = needs_kicad     # every test here resolves or writes through pcbnew


def _plan(outright=False):
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"), fields={"Pm.Height": "1.1mm"}),
           footprint("T1", 24, 20, w=2, h=1, inst="t1", nets=("B", "GND"), fields={"Pm.Height": "3mm"}),
           footprint("N1", 30, 30, w=2, h=1, inst="n1", nets=("C", "GND"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5, keep_going=True)
    if outright:
        b.keepout(Circle(8.0), "ring", at=Location(20, 20), excludes=("parts",), layers=[CopperLayer.F], why="clear")
    else:
        b.keepout(Circle(8.0), "ring", at=Location(20, 20), excludes=("parts",), max_height=1.9,
                  layers=[CopperLayer.F], why="the case leaves 1.9 mm here")
    for p, at in (("c1", (20, 20)), ("t1", (24, 20)), ("n1", (30, 30))):
        b.place(Part(p), at=Location(*at))
    return b.resolve()


def test_a_height_keepout_forbids_only_the_parts_it_does_not_admit():
    from placemat.kicad.write import keepout_rules
    [rule] = keepout_rules(_plan(), ["C1", "N1", "T1"], (CopperLayer.F, CopperLayer.B))
    assert rule.area == "keepout ring" and rule.layer == "F.Cu"
    assert rule.refs == ("N1", "T1")                  # too tall, and no Pm.Height; C1 is admitted
    text = rule.text()
    assert "(constraint disallow footprint)" in text
    assert "A.intersectsArea('keepout ring')" in text and "A.Layer == 'F.Cu'" in text
    assert "A.Reference == 'T1'" in text and "'C1'" not in text


def test_a_keepout_admitting_every_part_writes_no_rule():
    from placemat.kicad.write import keepout_rules
    assert keepout_rules(_plan(), ["C1"], (CopperLayer.F, CopperLayer.B)) == []


def test_a_keepout_excluding_parts_outright_writes_no_rule():
    from placemat.kicad.write import keepout_rules
    assert keepout_rules(_plan(outright=True), ["C1", "N1", "T1"], (CopperLayer.F, CopperLayer.B)) == []


@needs_kicad
def test_the_rule_area_allows_footprints_only_when_the_keepout_admits_some():
    import pcbnew
    from placemat.kicad.write import _draw_keepouts
    for outright, forbids in ((False, False), (True, True)):
        board = pcbnew.CreateEmptyBoard()
        _draw_keepouts(board, _plan(outright))
        [z] = [z for z in board.Zones() if z.GetIsRuleArea()]
        assert z.GetDoNotAllowFootprints() is forbids, outright


def _kicad_board(path):
    """A real board with C1 (short) and T1 (tall) inside the keepout's
    circle, each a footprint with one front pad and a courtyard."""
    import pcbnew
    board = pcbnew.CreateEmptyBoard()
    mm = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
    for ref, x in (("C1", 20.0), ("T1", 24.0)):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPosition(mm(x, 20))
        pad = pcbnew.PAD(fp)
        pad.SetShape(pcbnew.PAD_SHAPE_RECT)
        pad.SetSize(mm(1, 1))
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        ls = pcbnew.LSET()
        ls.AddLayer(pcbnew.F_Cu)
        pad.SetLayerSet(ls)
        pad.SetPosition(mm(x, 20))
        fp.Add(pad)
        crt = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_RECT)
        crt.SetStart(mm(x - 1, 19.5))
        crt.SetEnd(mm(x + 1, 20.5))
        crt.SetLayer(pcbnew.F_CrtYd)
        fp.Add(crt)
        board.Add(fp)
    return board


@needs_kicad
def test_kicads_own_drc_reports_the_tall_part_and_not_the_short_one(tmp_path):
    import json
    import subprocess
    from placemat.kicad.write import _draw_keepouts, keepout_rules
    from placemat.rules import write_rules
    plan = _plan()
    pcb = tmp_path / "layout.kicad_pcb"
    board = _kicad_board(pcb)
    _draw_keepouts(board, plan)
    board.Save(str(pcb))
    write_rules(str(pcb), keepout_rules(plan, ["C1", "T1"], (CopperLayer.F, CopperLayer.B)))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    data = json.loads(report.read_text())
    ruled = [v for v in data.get("violations", []) if "keepout ring" in v.get("description", "")]
    named = [i.get("description", "") for v in ruled for i in v.get("items", [])]
    assert any("T1" in d for d in named), ruled
    assert not any("C1" in d for d in named), ruled
    from placemat.kicad.drc import count_violations
    counted, permitted = count_violations(data, {"ring": ({"C1"}, set())})
    assert counted.get("items_not_allowed") == 1 and not permitted      # the tall part is a real violation
