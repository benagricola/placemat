"""A fragment carries facts for the board that stamps it (its faces, its clearance rules) as texts. The
transport never shows on the stamping board: whichever way the texts sit in it, in the cell's group or
loose, the parent reads them and its written board has none. A fragment run alone keeps its own."""
import pcbnew

from placemat.kicad.read import FACES_PREFIX, read_board
from placemat.kicad.write import apply_plan, strip_stamped_notes, write_faces
from placemat.layout import Board
from placemat.rules import RULE_PREFIX, parse_rule_note, rule_note
from placemat.values import Net
from tests.conftest import needs_kicad
from tests.test_stamped_rules import MODULE_RULE, _cell_board

OTHER_FACES = FACES_PREFIX + "outward=E"


def _note(board, text, x, y, group=None):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetLayer(pcbnew.Cmts_User)
    t.SetPosition(pcbnew.VECTOR2I(int(x * 1e6), int(y * 1e6)))
    board.Add(t)
    if group is not None:
        group.AddItem(t)
    return t


def _with_notes(tmp_path, grouped: bool):
    """A stamped board: the cell `cell`, and its faces and rule notes in its group (as pcb layout stamps
    them) or loose on the board."""
    pcb = _cell_board(tmp_path, notes=False)
    b = pcbnew.LoadBoard(str(pcb))
    (cell,) = list(b.Groups())
    g = cell if grouped else None
    _note(b, FACES_PREFIX + "outward=N quiet=S", 10, 40, g)
    _note(b, rule_note(MODULE_RULE), 10, 42, g)
    b.Save(str(pcb))
    return pcb


def _notes(pcb):
    return [d.GetText() for d in pcbnew.LoadBoard(str(pcb)).GetDrawings()
            if isinstance(d, pcbnew.PCB_TEXT) and d.GetText().startswith(("placemat faces", "placemat rule"))]


@needs_kicad
def test_the_parent_reads_the_facts_of_notes_in_the_cells_group_and_writes_none_of_them(tmp_path):
    pcb = _with_notes(tmp_path, grouped=True)
    (cell,) = read_board(pcb).cells.values()
    assert cell.faces == {"outward": "N", "quiet": "S"} and cell.rules == (MODULE_RULE,)
    plan = Board(read_board(pcb), edge_margin=0.0, keep_going=True).resolve()
    apply_plan(pcb, plan)
    assert _notes(pcb) == []
    assert (tmp_path / "layout.kicad_dru").exists() and "(constraint clearance (min 0.1mm))" in (tmp_path / "layout.kicad_dru").read_text()


@needs_kicad
def test_a_note_loose_on_the_parent_is_dropped_too(tmp_path):
    pcb = _with_notes(tmp_path, grouped=False)
    plan = Board(read_board(pcb), edge_margin=0.0, keep_going=True).resolve()
    apply_plan(pcb, plan)
    assert _notes(pcb) == []


@needs_kicad
def test_the_unplaced_generation_is_cleared_of_notes_once_they_are_read(tmp_path):
    pcb = _with_notes(tmp_path, grouped=True)
    before = read_board(pcb)
    assert _notes(pcb)
    strip_stamped_notes(pcb)
    assert _notes(pcb) == []
    after = pcbnew.LoadBoard(str(pcb))
    (cell,) = list(after.Groups())
    assert len(list(cell.GetItems())) == 2                  # its parts are still its members
    assert [fp.GetReference() for fp in after.GetFootprints()] == [fp.ref for fp in before.footprints]


@needs_kicad
def test_a_fragment_run_alone_keeps_the_faces_it_was_stamped_with_and_writes_its_rules(tmp_path):
    pcb = _cell_board(tmp_path, notes=False)
    write_faces(pcb, {"outward": "N"})
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    b.rect(20, 20, draw=False)
    b.rule(clearance=0.1, between=(Net("cell.A"), Net("cell.B")), why="declared in the module")
    apply_plan(pcb, b.resolve())
    notes = _notes(pcb)
    assert sorted(n.split(" clearance")[0] for n in notes) == ["placemat faces outward=N", "placemat rule"]
    assert parse_rule_note([n for n in notes if n.startswith(RULE_PREFIX)][0]).min_mm == 0.1


@needs_kicad
def test_a_fragment_that_declares_its_faces_writes_them_once(tmp_path):
    from placemat.values import Edge
    pcb = _cell_board(tmp_path, notes=False)
    write_faces(pcb, {"outward": "S"})
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    b.rect(20, 20, draw=False)
    b.faces(outward=Edge.NORTH)
    apply_plan(pcb, b.resolve())
    assert _notes(pcb) == ["placemat faces outward=N"]


@needs_kicad
def test_a_fragment_that_stamps_a_cell_writes_the_cells_rule_once_as_its_own_and_not_the_cells_faces(tmp_path):
    pcb = _with_notes(tmp_path, grouped=True)
    b = Board(read_board(pcb), edge_margin=0.0, keep_going=True)
    b.rect(40, 40, draw=False)
    apply_plan(pcb, b.resolve())
    (note,) = _notes(pcb)                                      # the cell's rule, carried on as the fragment's own
    assert note.startswith(RULE_PREFIX) and " within=cell " in note
    (grouped,) = [d for d in pcbnew.LoadBoard(str(pcb)).GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)]
    assert grouped.GetParentGroup() is None


@needs_kicad
def test_a_fragments_own_faces_survive_the_clearing_of_the_generation(tmp_path):
    pcb = _with_notes(tmp_path, grouped=True)
    b = pcbnew.LoadBoard(str(pcb))
    _note(b, OTHER_FACES, 0, 50)                               # loose: the fragment's own
    b.Save(str(pcb))
    assert strip_stamped_notes(pcb, keep_loose_faces=True) == 2
    assert _notes(pcb) == [OTHER_FACES]
    assert strip_stamped_notes(pcb) == 1
    assert _notes(pcb) == []
