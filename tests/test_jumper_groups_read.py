"""The pads a part joins inside its package, read from the board (KiCad 10
jumper_pad_groups and duplicate_pad_numbers_are_jumpers)."""
from tests.conftest import needs_kicad

pytestmark = [needs_kicad]

BOARD = """(kicad_pcb (version 20241229) (generator "pcbnew")
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))
  (net 0 "") (net 1 "DP") (net 2 "DN") (net 3 "SHIELD")
  (footprint "test:esd" (layer "F.Cu") (at 10 10)
    (property "Reference" "U1" (at 0 -2 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
    {groups}
    (pad "1" smd rect (at -0.5 -0.7) (size 0.3 0.5) (layers "F.Cu") (net 1 "DP"))
    (pad "3" smd rect (at 0.5 -0.7) (size 0.3 0.5) (layers "F.Cu") (net 2 "DN"))
    (pad "4" smd rect (at 0.5 0.7) (size 0.3 0.5) (layers "F.Cu") (net 2 "DN"))
    (pad "6" smd rect (at -0.5 0.7) (size 0.3 0.5) (layers "F.Cu") (net 1 "DP")))
  (footprint "test:shell" (layer "F.Cu") (at 20 10)
    (property "Reference" "U3" (at 0 -2 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
    {duplicates}
    (pad "1" smd rect (at -2 0) (size 0.5 0.5) (layers "F.Cu") (net 3 "SHIELD"))
    (pad "1" smd rect (at 2 0) (size 0.5 0.5) (layers "F.Cu") (net 3 "SHIELD")))
  (gr_rect (start 0 0) (end 30 20) (layer "Edge.Cuts") (stroke (width 0.1) (type solid)))
)
"""


def _read(tmp_path, **kw):
    from placemat.kicad.read import read_board
    path = tmp_path / "board.kicad_pcb"
    path.write_text(BOARD.format(groups=kw.get("groups", ""), duplicates=kw.get("duplicates", "")))
    return read_board(str(path))


def test_jumper_pad_groups_and_duplicate_numbers_are_read(tmp_path):
    g = _read(tmp_path, groups='(jumper_pad_groups ("1" "6") ("3" "4"))',
              duplicates="(duplicate_pad_numbers_are_jumpers yes)")
    assert g.footprint("U1").jumper_groups == (("1", "6"), ("3", "4"))
    assert g.footprint("U3").jumper_groups == (("1",),)


def test_a_part_without_groups_has_none(tmp_path):
    g = _read(tmp_path)
    assert g.footprint("U1").jumper_groups == () and g.footprint("U3").jumper_groups == ()
