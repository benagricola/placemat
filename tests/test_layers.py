"""What copper layers placemat can name, and what it does with a board that
has more of them than it expects."""
import pytest

from placemat.values import CopperLayer, Face
from tests.conftest import needs_kicad


def test_every_layer_kicad_can_have_is_nameable():
    """KiCad's maximum is 32 copper layers: the two faces and In1 to In30."""
    assert len(CopperLayer) == 32
    assert CopperLayer.of("In30.Cu").value == "In30.Cu"
    assert CopperLayer.of("In7.Cu") is CopperLayer.IN7


def test_the_faces_keep_their_names_and_their_faces():
    assert CopperLayer.F.value == "F.Cu" and CopperLayer.B.value == "B.Cu"
    assert CopperLayer.F.face is Face.FRONT and CopperLayer.B.face is Face.BACK
    assert CopperLayer.F.other_face is CopperLayer.B
    assert CopperLayer.B.other_face is CopperLayer.F


def test_an_inner_layer_has_no_face_and_no_opposite():
    assert CopperLayer.IN7.face is None
    with pytest.raises(ValueError, match="inner layer"):
        CopperLayer.IN7.other_face


def test_a_layer_that_is_not_copper_is_refused_by_name():
    with pytest.raises(ValueError, match="F.SilkS"):
        CopperLayer.of("F.SilkS")
    with pytest.raises(ValueError, match="In31.Cu"):
        CopperLayer.of("In31.Cu")          # past KiCad's own maximum


def test_a_layer_is_still_a_string_and_still_hashable():
    """Everything downstream treats a layer as its KiCad name."""
    assert isinstance(CopperLayer.IN7, str) and CopperLayer.IN7 == "In7.Cu"
    assert len(frozenset([CopperLayer.F, CopperLayer.IN7, CopperLayer.F])) == 2
    assert CopperLayer.of(CopperLayer.IN7) is CopperLayer.IN7


def _board_with(tmp_path, copper_layers, tracks):
    """A board of `copper_layers` copper layers carrying a track on each of
    `tracks` (pcbnew layer ids), saved and handed back as a path."""
    import pcbnew
    b = pcbnew.CreateEmptyBoard()
    b.SetCopperLayerCount(copper_layers)

    def vec(x, y):
        return pcbnew.VECTOR2I(int(x * 1e6), int(y * 1e6))

    for a, c in (((0, 0), (40, 0)), ((40, 0), (40, 40)), ((40, 40), (0, 40)), ((0, 40), (0, 0))):
        s = pcbnew.PCB_SHAPE(b, pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(100000)
        s.SetStart(vec(*a))
        s.SetEnd(vec(*c))
        b.Add(s)
    net = pcbnew.NETINFO_ITEM(b, "SIG")
    b.Add(net)
    for n, layer in enumerate(tracks):
        t = pcbnew.PCB_TRACK(b)
        t.SetLayer(layer)
        t.SetWidth(200000)
        t.SetStart(vec(5.0, 5.0 + n))
        t.SetEnd(vec(30.0, 5.0 + n))
        t.SetNetCode(net.GetNetCode())
        b.Add(t)
    path = tmp_path / "stack.kicad_pcb"
    b.Save(str(path))
    return path


@needs_kicad
def test_a_six_layer_board_reads_as_six_layers(tmp_path):
    """The defect this fixes: In3 and In4 used to be dropped on the floor,
    and an item on one of them came back belonging to no layer at all."""
    import pcbnew
    from placemat.kicad.read import read_board
    pcb = _board_with(tmp_path, 6, [pcbnew.In1_Cu, pcbnew.In3_Cu])
    g = read_board(pcb)
    assert [l.value for l in g.layers] == ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"]
    on = sorted(sorted(x.value for x in c.layers) for c in g.copper if c.kind == "track")
    assert on == [["In1.Cu"], ["In3.Cu"]]


@needs_kicad
def test_a_thirty_two_layer_board_reads_as_thirty_two(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    pcb = _board_with(tmp_path, 32, [pcbnew.In30_Cu])
    g = read_board(pcb)
    assert len(g.layers) == 32
    assert g.layers[0] is CopperLayer.F and g.layers[-1] is CopperLayer.B
    (track,) = [c for c in g.copper if c.kind == "track"]
    assert track.layers == frozenset([CopperLayer.IN30])


@needs_kicad
def test_a_two_layer_board_is_unchanged(tmp_path):
    import pcbnew
    from placemat.kicad.read import read_board
    pcb = _board_with(tmp_path, 2, [pcbnew.F_Cu])
    g = read_board(pcb)
    assert [l.value for l in g.layers] == ["F.Cu", "B.Cu"]


@needs_kicad
def test_a_copper_layer_that_cannot_be_named_is_not_dropped(monkeypatch):
    """Naming every layer fixed the symptom; this is the defence. The reader
    used to swallow a copper layer it had no member for, which is how a
    six-layer board came back as four without a word. A layer that is not
    copper is still skipped - that is the job - but one that is copper and
    unnameable is an error."""
    from placemat.kicad import read as R
    monkeypatch.setattr(R, "_layer_names", lambda board, ls: ["F.Cu", "F.SilkS", "F.Mask"])
    assert R._copper_layers(None, None) == frozenset([CopperLayer.F])

    monkeypatch.setattr(R, "_layer_names", lambda board, ls: ["F.Cu", "In44.Cu"])
    with pytest.raises(ValueError, match="In44.Cu"):
        R._copper_layers(None, None)
