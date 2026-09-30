"""Per-layer copper thickness, read from the .kicad_pcb's own (stackup
...) block: pcbnew's BOARD_STACKUP is not wrapped for Python on this
build (GetStackupDescriptor()/GetStackupOrDefault() come back as a bare
SwigPyObject with no methods), so this reads the board's own text."""
from placemat.kicad.read import stackup_copper_mm
from placemat.values import CopperLayer
from tests.conftest import needs_kicad

F, B, IN1, IN2 = CopperLayer.F, CopperLayer.B, CopperLayer.IN1, CopperLayer.IN2

_STACKUP_PCB = """(kicad_pcb
  (setup
    (stackup
      (layer "F.SilkS" (type "Top Silk Screen"))
      (layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))
      (layer "F.Cu" (type "copper") (thickness 0.035))
      (layer "dielectric 1" (type "core") (thickness 1.51) (material "FR4"))
      (layer "In1.Cu" (type "copper") (thickness 0.0152))
      (layer "dielectric 2" (type "core") (thickness 1.51) (material "FR4"))
      (layer "B.Cu" (type "copper") (thickness 0.035))
    )
  )
)
"""

_NO_STACKUP_PCB = "(kicad_pcb (setup (pad_to_mask_clearance 0)))\n"


def test_each_copper_layers_thickness_is_read_in_mm(tmp_path):
    p = tmp_path / "layout.kicad_pcb"
    p.write_text(_STACKUP_PCB)
    assert stackup_copper_mm(p) == {F: 0.035, IN1: 0.0152, B: 0.035}


def test_a_board_with_no_stackup_block_gives_no_weights(tmp_path):
    """A board whose .zen declares no stackup: KiCad writes no (stackup
    ...) block at all (m_HasStackup is false), confirmed by saving a
    fresh CreateEmptyBoard() and reading it back."""
    p = tmp_path / "layout.kicad_pcb"
    p.write_text(_NO_STACKUP_PCB)
    assert stackup_copper_mm(p) == {}


@needs_kicad
def test_read_board_carries_the_stackups_copper_weight(tmp_path):
    """End to end through read_board: a hand-built stackup block, spliced
    into a real pcbnew-written board (pcbnew cannot write BOARD_STACKUP
    either, so the splice is textual, the same as production reads it)."""
    import pcbnew
    from placemat.kicad.read import read_board
    board = pcbnew.CreateEmptyBoard()
    board.SetCopperLayerCount(4)
    p = tmp_path / "layout.kicad_pcb"
    board.Save(str(p))
    text = p.read_text()
    stack = ('\t\t(stackup\n\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))\n'
             '\t\t\t(layer "In1.Cu" (type "copper") (thickness 0.0152))\n'
             '\t\t\t(layer "In2.Cu" (type "copper") (thickness 0.0152))\n'
             '\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))\n\t\t)\n')
    assert "\t\t(pad_to_mask_clearance" in text
    text = text.replace("\t\t(pad_to_mask_clearance", stack + "\t\t(pad_to_mask_clearance")
    p.write_text(text)
    g = read_board(p)
    assert g.copper_mm[IN1] == 0.0152 and g.copper_mm[F] == 0.035
