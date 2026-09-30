"""What a keepout's own drawing says on the board: its outline and what it
admits, on the Fab layer of its face (or User.Comments), in placemat's own
`keepout drawings` group, replaced whole on every write."""
from placemat.cutouts import Circle
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import CopperLayer, Location, Part
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint


def _height_board(**kw):
    kw.setdefault("settings", Settings(write_keepout_drawings="admitting"))
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"), fields={"Pm.Height": "1.1mm"})]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5, **kw)
    b.keepout(Circle(8.0), "ring", at=Location(20, 20), excludes=("parts",), max_height=1.9,
              layers=[CopperLayer.F], why="the case leaves 1.9 mm here")
    b.place(Part("c1"), at=Location(20, 20))
    return b


def _drawn(plan, copper_layers=2):
    import pcbnew
    from placemat.kicad.write import _draw_keepout_drawings
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(copper_layers)
    _draw_keepout_drawings(board, plan)
    return board


@needs_kicad
def test_an_admitting_keepout_draws_an_outline_and_a_label():
    import pcbnew
    plan = _height_board().resolve()
    board = _drawn(plan)
    shapes = [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_SHAPE)]
    texts = [d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT)]
    assert len(shapes) == 1 and len(texts) == 1
    assert texts[0].GetText() == "ring: parts <= 1.90 mm"
    assert shapes[0].GetLayer() == pcbnew.F_Fab and texts[0].GetLayer() == pcbnew.F_Fab


@needs_kicad
def test_a_label_names_the_keepout_and_its_height_and_no_parts():
    import pcbnew
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"), fields={"Pm.Height": "1.1mm"}),
           footprint("C2", 25, 20, w=2, h=1, inst="c2", nets=("A", "GND"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5,
              settings=Settings(write_keepout_drawings="admitting"))
    b.keepout(Circle(10.0), "ring", at=Location(21, 20), excludes=("parts",), max_height=1.9,
              layers=[CopperLayer.F], allow=(Part("c2"),), why="the case, and c2 is bolted through it")
    b.place(Part("c1"), at=Location(20, 20))
    b.place(Part("c2"), at=Location(25, 20))
    plan = b.resolve()
    board = _drawn(plan)
    text = next(d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_TEXT))
    assert text.GetText() == "ring: parts <= 1.90 mm"          # the parts it names are the rule's, not text's


@needs_kicad
def test_they_share_one_group_replaced_whole_on_a_rerun_with_fewer_keepouts():
    import pcbnew
    from placemat.kicad.write import _draw_keepout_drawings
    plan = _height_board().resolve()
    board = _drawn(plan)
    groups = [g for g in board.Groups() if g.GetName() == "keepout drawings"]
    assert len(groups) == 1 and len(list(groups[0].GetItems())) == 2
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"), fields={"Pm.Height": "1.1mm"})]
    b2 = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)   # no keepout this time
    b2.place(Part("c1"), at=Location(20, 20))
    _draw_keepout_drawings(board, b2.resolve())
    groups = [g for g in board.Groups() if g.GetName() == "keepout drawings"]
    assert groups == [] or len(list(groups[0].GetItems())) == 0
    assert not [d for d in board.GetDrawings() if isinstance(d, (pcbnew.PCB_SHAPE, pcbnew.PCB_TEXT))]


@needs_kicad
def test_a_keepout_admitting_nothing_is_not_drawn_by_default_and_is_drawn_under_all():
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"))]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5)
    b.keepout(Circle(8.0), "quiet", at=Location(20, 20), why="clearance")
    plan = b.resolve()
    board = _drawn(plan)
    assert not list(board.GetDrawings())
    b_all = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5,
                  settings=Settings(write_keepout_drawings="all"))
    b_all.keepout(Circle(8.0), "quiet", at=Location(20, 20), why="clearance")
    plan_all = b_all.resolve()
    board_all = _drawn(plan_all)
    assert len(list(board_all.GetDrawings())) == 2


@needs_kicad
def test_write_keepout_drawings_none_draws_nothing():
    b = _height_board(settings=Settings(write_keepout_drawings="none"))
    plan = b.resolve()
    board = _drawn(plan)
    assert not list(board.GetDrawings())


@needs_kicad
def test_both_face_keepouts_go_on_user_comments():
    import pcbnew
    fps = [footprint("C1", 20, 20, w=2, h=1, inst="c1", nets=("A", "GND"), fields={"Pm.Height": "1.1mm"})]
    b = Board(board_geometry(fps, width=40, height=40), edge_margin=0.5,
              settings=Settings(write_keepout_drawings="admitting"))
    b.keepout(Circle(8.0), "ring", at=Location(20, 20), excludes=("parts",), max_height=1.9, why="x")
    plan = b.resolve()
    board = _drawn(plan, copper_layers=2)          # layers=None: every copper layer the board has -> both faces
    shape = next(d for d in board.GetDrawings() if isinstance(d, pcbnew.PCB_SHAPE))
    assert shape.GetLayer() == pcbnew.Cmts_User


@needs_kicad
def test_a_stamped_fragments_own_nested_group_is_left_alone():
    """A stamped fragment's own keepout drawing, still nested in its cell's
    group at this point in the write (before _write_groups lifts nested
    groups), is not placemat's `keepout drawings` group to replace: only a
    TOP-LEVEL group by that name is ours."""
    import pcbnew
    from placemat.kicad.write import _draw_keepout_drawings
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(2)
    cell = pcbnew.PCB_GROUP(board)
    cell.SetName("m")
    board.Add(cell)
    nested = pcbnew.PCB_GROUP(board)
    nested.SetName("keepout drawings")
    board.Add(nested)
    cell.AddItem(nested)
    fragment_text = pcbnew.PCB_TEXT(board)
    fragment_text.SetText("shield: GND copper")
    fragment_text.SetLayer(pcbnew.F_Fab)
    board.Add(fragment_text)
    nested.AddItem(fragment_text)

    plan = _height_board().resolve()
    _draw_keepout_drawings(board, plan)

    assert fragment_text.GetText() == "shield: GND copper"       # untouched
    groups = {g.GetName(): g for g in board.Groups() if g.GetParentGroup() is None}
    assert "keepout drawings" in groups
    assert list(groups["keepout drawings"].GetItems())           # placemat's own, top-level, holds the new drawing
    still_nested = [g for g in board.Groups()
                    if g.GetParentGroup() is not None and g.GetParentGroup().GetName() == "m"]
    assert len(still_nested) == 1 and still_nested[0].GetName() == "keepout drawings"


@needs_kicad
def test_by_default_no_keepout_is_drawn():
    """A keepout is a KiCad rule area, and its .kicad_dru rule says what it
    admits: by default nothing restates it as board text."""
    import pcbnew
    plan = _height_board(settings=Settings()).resolve()
    board = _drawn(plan)
    assert not [d for d in board.GetDrawings() if isinstance(d, (pcbnew.PCB_TEXT, pcbnew.PCB_SHAPE))]
