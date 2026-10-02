"""A stamped cell brings the clearance rules its module declared, as it brings its keepouts: the fragment
carries each as a note that pcb layout stamps with the cell, and the board that stamps it judges and writes
them, held to the cell and over the nets as it names them."""
import dataclasses
import json
import subprocess

from placemat.layout import Board
from placemat.rules import RULE_PREFIX, Rule, parse_rule_note, rule_note, rules_text
from placemat.values import Net
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint

MODULE_RULE = Rule("clearance", 0.10, "fine-pitch grid: the pad pitch leaves 0.10 between copper", between=("A", "B"))


def test_a_rule_round_trips_through_its_note():
    for rule in (MODULE_RULE,
                 Rule("clearance", 0.15, "on a net: {braces}, $dollars and 100% \"quotes\"", on="NET,1"),
                 Rule("clearance", 0.2, "a cell", within="sub")):
        note = rule_note(rule)
        assert note.startswith(RULE_PREFIX) and "{" not in note and "$" not in note and '"' not in note
        assert parse_rule_note(note) == rule


def test_a_text_that_is_not_a_rule_note_reads_as_none():
    assert parse_rule_note("placemat faces outward=N") is None
    assert parse_rule_note(RULE_PREFIX + "clearance=x between=A,B why=w") is None
    assert parse_rule_note(RULE_PREFIX + "clearance=0.1 why=no%20scope") is None


def _parent(module_rules=(MODULE_RULE,), nets=("cell.A", "cell.B")):
    """A board holding one stamped cell `cell` (two parts on its nets) and a loose part on the same nets."""
    fps = [footprint("C1", 10, 10, cell="cell", inst="cell.c1", nets=(nets[0], "GND")),
           footprint("C2", 20, 10, cell="cell", inst="cell.c2", nets=(nets[1], "GND")),
           footprint("R9", 30, 30, nets=(nets[0], nets[1]))]
    g = board_geometry(fps, cells=["cell"], extra_nets=("GND",))
    cell = dataclasses.replace(g.cells["cell"], rules=tuple(module_rules))
    return dataclasses.replace(g, cells={**g.cells, "cell": cell})


def test_the_parent_judges_the_cells_copper_by_the_modules_rule():
    b = Board(_parent(), edge_margin=1.0)
    (rule,) = b._rules
    assert rule.min_mm == 0.10 and rule.within == "cell" and rule.between == ("cell.A", "cell.B")
    assert rule.why.endswith("[cell]") and "fine-pitch grid" in rule.why
    assert b._clearance("cell.A", "cell.B", "C1", "C2") == 0.10           # both in the cell
    assert b._clearance("cell.A", "cell.B", "C1", "R9") == 0.2                 # a part outside it: the class figure
    assert b._clearance("cell.A", "GND", "C1", "C2") == 0.2               # other nets: the class figure


def test_the_parents_own_rule_on_the_same_pair_wins():
    b = Board(_parent(), edge_margin=1.0)
    b.rule(clearance=0.14, between=(Net("cell.A"), Net("cell.B")), why="this board's own figure")
    assert b._clearance("cell.A", "cell.B", "C1", "C2") == 0.14
    assert [r.min_mm for r in b._rules] == [0.10, 0.14]                             # the module's first: the later decides
    plan = b.resolve()
    assert [r.min_mm for r in plan.rules] == [0.10, 0.14]


def test_the_rule_is_written_to_the_parents_rules_file_held_to_its_cell():
    plan = Board(_parent(), edge_margin=1.0).resolve()
    text = rules_text(plan.rules)
    assert "A.memberOf('cell') && B.memberOf('cell') && ((A.NetName == 'cell.A' && B.NetName == 'cell.B')" in text
    assert "(constraint clearance (min 0.1mm))" in text


def test_a_rule_whose_net_the_board_lacks_is_not_carried_and_is_said():
    plan = Board(_parent([Rule("clearance", 0.1, "gone", between=("A", "NOPE"))]), edge_margin=1.0).resolve()
    assert plan.rules == []
    assert any("'gone' from the cell cell is not carried" in f and "NOPE" in f for f in plan.findings)


def test_a_module_rule_within_one_of_its_cells_takes_that_cells_stamped_group():
    fps = [footprint("C1", 10, 10, cell="cell.sub", inst="cell.sub.c1", nets=("cell.A", "GND"))]
    g = board_geometry(fps, cells=["cell.sub", "cell"], extra_nets=("GND",))
    cell = dataclasses.replace(g.cells["cell"], rules=(Rule("clearance", 0.1, "inner", within="sub"),
                                                       Rule("clearance", 0.1, "gone", within="nope")))
    g = dataclasses.replace(g, cells={**g.cells, "cell": cell})
    plan = Board(g, edge_margin=1.0).resolve()
    assert [r.within for r in plan.rules] == ["cell.sub"]
    assert any("cell nope is not on this board" in f for f in plan.findings)


def test_a_board_declaring_no_rule_over_a_cell_with_none_has_none():
    assert Board(_parent([]), edge_margin=1.0)._rules == []


# --- against pcbnew and kicad-cli ------------------------------------------------------------------

GAP = 0.12


def _cell_board(tmp_path, notes=True):
    """What a parent looks like after pcb layout stamps a fragment: a group `cell` holding two parts whose
    pads on `cell.A` and `cell.B` stand 0.12 mm apart, and the fragment's rule note."""
    import pcbnew
    from placemat.kicad.write import write_rule_notes
    mm = pcbnew.FromMM
    b = pcbnew.CreateEmptyBoard()
    nets = {}
    grp = pcbnew.PCB_GROUP(b)
    grp.SetName("cell")
    b.Add(grp)
    for ref, x, n in (("C1", 10.0, "cell.A"), ("C2", 10.0 + 0.5 + GAP, "cell.B")):
        fp = pcbnew.FOOTPRINT(b)
        fp.SetReference(ref)
        fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(10)))
        p = pcbnew.PAD(fp)
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetSize(pcbnew.VECTOR2I(mm(0.5), mm(0.5)))
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        ls = pcbnew.LSET()
        ls.AddLayer(pcbnew.F_Cu)
        p.SetLayerSet(ls)
        p.SetPosition(pcbnew.VECTOR2I(mm(x), mm(10)))
        p.SetNumber("1")
        nets[n] = pcbnew.NETINFO_ITEM(b, n)
        b.Add(nets[n])
        p.SetNet(nets[n])
        fp.Add(p)
        b.Add(fp)
        grp.AddItem(fp)
    if notes:
        write_rule_notes(b, [MODULE_RULE])
        for d in b.GetDrawings():
            if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(RULE_PREFIX):
                grp.AddItem(d)
    pcb = tmp_path / "layout.kicad_pcb"
    b.Save(str(pcb))
    (tmp_path / "layout.kicad_pro").write_text("{}")
    return pcb


def _clearance_violations(pcb):
    out = pcb.with_suffix(".json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--output", str(out), str(pcb)],
                   capture_output=True, timeout=120)
    return [v for v in json.loads(out.read_text())["violations"] if v["type"] == "clearance"]


def _write_parent(pcb):
    from placemat.kicad.read import read_board
    from placemat.kicad.write import apply_plan
    plan = Board(read_board(pcb), edge_margin=0.0, keep_going=True).resolve()
    apply_plan(pcb, plan)
    return plan


@needs_kicad
def test_a_cell_carries_its_note_into_the_parent_where_it_is_read():
    import pathlib
    import tempfile
    from placemat.kicad.read import read_board
    with tempfile.TemporaryDirectory() as d:
        (cell,) = read_board(_cell_board(pathlib.Path(d))).cells.values()
    assert cell.rules == (MODULE_RULE,)


@needs_kicad
def test_the_parents_kicad_dru_carries_the_rule_and_its_drc_passes_the_cells_copper(tmp_path):
    pcb = _cell_board(tmp_path)
    plan = _write_parent(pcb)
    dru = (tmp_path / "layout.kicad_dru").read_text()
    assert "A.memberOf('cell') && B.memberOf('cell')" in dru and "A.NetName == 'cell.A'" in dru
    assert "(constraint clearance (min 0.1mm))" in dru
    assert [r.min_mm for r in plan.rules] == [0.10]
    assert _clearance_violations(pcb) == []


@needs_kicad
def test_without_the_note_kicad_judges_the_same_copper_at_the_class_clearance(tmp_path):
    pcb = _cell_board(tmp_path, notes=False)
    _write_parent(pcb)
    assert not (tmp_path / "layout.kicad_dru").exists()
    assert _clearance_violations(pcb)


@needs_kicad
def test_the_stamped_note_does_not_stay_on_the_written_parent(tmp_path):
    import pcbnew
    pcb = _cell_board(tmp_path)
    _write_parent(pcb)
    texts = [d.GetText() for d in pcbnew.LoadBoard(str(pcb)).GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)]
    assert not [t for t in texts if t.startswith(RULE_PREFIX)]


@needs_kicad
def test_a_fragment_writes_its_rules_as_notes_and_a_rule_of_a_part_is_left_to_the_part(tmp_path):
    import pcbnew
    from placemat.kicad.write import write_rule_notes
    b = pcbnew.CreateEmptyBoard()
    of = Rule("clearance", 0.3, "u1 keep-out", between=("X", "Y"), of="U1")
    texts = write_rule_notes(b, [MODULE_RULE, of])
    assert texts == [rule_note(MODULE_RULE)]
    assert write_rule_notes(b, [MODULE_RULE]) == texts                      # a rerun replaces them, never doubles them
    assert len([d for d in b.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)]) == 1
    assert write_rule_notes(b, []) == []
    assert not list(b.GetDrawings())


@needs_kicad
def test_a_fragments_run_writes_its_rules_into_the_board_and_a_board_run_does_not(tmp_path):
    import pcbnew
    from placemat.kicad.write import apply_plan
    from placemat.kicad.read import read_board
    for draw, expected in ((False, 1), (True, 0)):
        pcb = _cell_board(tmp_path, notes=False)
        b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
        b.size(20, 20, draw=draw)
        b.rule(clearance=0.1, between=(Net("cell.A"), Net("cell.B")), why="declared in the module")
        apply_plan(pcb, b.resolve())
        notes = [d.GetText() for d in pcbnew.LoadBoard(str(pcb)).GetDrawings()
                 if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(RULE_PREFIX)]
        assert len(notes) == expected, (draw, notes)
        if notes:
            (rule,) = [parse_rule_note(n) for n in notes]
            assert rule.min_mm == 0.1 and rule.between == ("cell.A", "cell.B") and rule.why == "declared in the module"
