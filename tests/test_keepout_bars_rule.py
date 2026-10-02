"""A keepout that names what it bars is written as a KiCad rule area that
allows footprints, and a .kicad_dru rule that forbids exactly the barred
references. Its drawn label is its name, never what it bars."""
from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint

pytestmark = needs_kicad     # every test here resolves or writes through pcbnew

STACK = (CopperLayer.F, CopperLayer.B)
REFS = ["J1", "J2", "M1", "N1", "T1"]


def _plan(bars=("m1",), max_height=None, name="cup"):
    heights = {"t1": "3mm", "j2": "1mm", "m1": "1mm"}
    fps = [footprint(i.upper(), 10.0 + n * 6.0, 50.0, w=2, h=1, inst=i, nets=("A", "GND"),
                     fields={"Pm.Height": heights[i]} if i in heights else None)
           for n, i in enumerate(("j1", "j2", "m1", "n1", "t1"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=0.5, keep_going=True)
    b.keepout(Circle(8.0), name, at=Location(20.0, 20.0), excludes=("parts",), layers=[CopperLayer.F],
              why="a part mounted off the board sits over it", bars=tuple(Part(i) for i in bars),
              max_height=max_height)
    for i, at in (("j1", (20, 20)), ("j2", (25, 20)), ("m1", (45, 45)), ("n1", (30, 40)), ("t1", (40, 40))):
        b.place(Part(i), at=Location(*at))
    return b.resolve()


def test_the_rule_forbids_exactly_the_barred_references():
    from placemat.kicad.write import keepout_rules
    [rule] = keepout_rules(_plan(bars=("m1", "j1")), REFS, STACK)
    assert rule.refs == ("J1", "M1")
    assert "A.intersectsArea('keepout cup')" in rule.text() and "A.Layer == 'F.Cu'" in rule.text()


def test_a_part_added_to_the_board_is_not_forbidden():
    from placemat.kicad.write import keepout_rules
    [rule] = keepout_rules(_plan(), REFS + ["X1"], STACK)
    assert rule.refs == ("M1",)


def test_the_rule_with_a_height_limit_forbids_the_barred_and_the_too_tall():
    from placemat.kicad.write import keepout_rules
    [rule] = keepout_rules(_plan(max_height=2.0), REFS, STACK)
    # M1 is short but barred; T1 is 3 mm; J1 and N1 have no Pm.Height; J2 is admitted
    assert rule.refs == ("J1", "M1", "N1", "T1")


@needs_kicad
def test_the_rule_area_allows_footprints():
    import pcbnew
    from placemat.kicad.write import _draw_keepouts
    board = pcbnew.CreateEmptyBoard()
    _draw_keepouts(board, _plan())
    [z] = [z for z in board.Zones() if z.GetIsRuleArea()]
    assert z.GetDoNotAllowFootprints() is False


def _drc_plan():
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND")),
           footprint("T1", 24, 20, w=2, h=1, inst="t1", nets=("B", "GND"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5, keep_going=True)
    b.keepout(Circle(8.0), "cup", at=Location(20.0, 20.0), excludes=("parts",), layers=[CopperLayer.F],
              why="a part mounted off the board sits over it", bars=(Part("c1"),))
    for p, at in (("c1", (20, 20)), ("t1", (24, 20))):
        b.place(Part(p), at=Location(*at))
    return b.resolve()


@needs_kicad
def test_kicads_own_drc_reports_the_barred_part_and_not_the_other(tmp_path):
    import json
    import subprocess
    from placemat.kicad.write import _draw_keepouts, keepout_rules
    from placemat.rules import write_rules
    from tests.test_keepout_admits_rule import _kicad_board
    plan = _drc_plan()
    pcb = tmp_path / "layout.kicad_pcb"
    board = _kicad_board(pcb)
    _draw_keepouts(board, plan)
    board.Save(str(pcb))
    write_rules(str(pcb), keepout_rules(plan, ["C1", "T1"], STACK))
    report = tmp_path / "drc.json"
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(report), str(pcb)],
                   capture_output=True, timeout=120)
    data = json.loads(report.read_text())
    ruled = [v for v in data.get("violations", []) if "keepout cup" in v.get("description", "")]
    named = [i.get("description", "") for v in ruled for i in v.get("items", [])]
    assert any("C1" in d for d in named), ruled
    assert not any("T1" in d for d in named), ruled


def _label(bars, **kw):
    import pcbnew
    from placemat.kicad.write import _draw_keepout_drawings
    board = pcbnew.CreateEmptyBoard()
    _draw_keepout_drawings(board, _plan(bars=bars, **kw))
    [t] = [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)]
    return t.GetText()


@needs_kicad
def test_a_label_names_the_keepout_and_never_what_it_bars():
    """The .kicad_dru rule names the barred parts; the label is the
    keepout's name, and its height limit when it has one."""
    assert _label(("m1",)) == "cup"
    assert _label(("m1", "j1", "j2", "n1")) == "cup"
    assert _label(("m1",), max_height=2.0) == "cup: parts <= 2.00 mm"
