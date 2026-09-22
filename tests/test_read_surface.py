"""The read surface against real boards: the standalone footprint reader, the
board's true outline, and the promise that this reader and the placer's agree."""
import glob
import hashlib
import os
import pathlib

import pytest

from placemat.kicad.read import read_board
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad]

FAIRING = "/home/ben/Documents/Hardware/fairing-instrument/electronics/boards/main/kicad/layout.kicad_pcb"
PARTS = "/home/ben/Documents/Hardware/fairing-instrument/electronics/parts"
needs_fairing = pytest.mark.skipif(not pathlib.Path(FAIRING).exists(),
                                   reason="the fairing main board is not here")
needs_parts = pytest.mark.skipif(not os.path.isdir(PARTS), reason="the fairing parts are not here")


def _one(pattern):
    hits = glob.glob(os.path.join(PARTS, pattern, "*.kicad_mod"))
    if not hits:
        pytest.skip("no footprint matching %s" % pattern)
    return hits[0]


@needs_breakout
def test_a_rectangular_board_reads_as_one_outline_with_no_holes(breakout_pcb):
    g = read_board(breakout_pcb)
    assert len(g.board_polygon) == 1
    assert len(g.board_polygon[0]) >= 4


@needs_breakout
def test_the_outline_box_agrees_with_the_polygon(breakout_pcb):
    """board_polygon is added beside outline, not instead of it; they must
    describe the same board."""
    from placemat.values import Box
    g = read_board(breakout_pcb)
    poly_box = Box.of_points(g.board_polygon[0])
    assert poly_box.width == pytest.approx(g.outline_box.width, abs=0.2)
    assert poly_box.height == pytest.approx(g.outline_box.height, abs=0.2)


@needs_fairing
def test_a_disc_with_a_bore_reads_as_a_curve_and_a_hole():
    """The case outline gets wrong: it holds one bounding box per Edge.Cuts
    drawing, so a disc reads as a square."""
    g = read_board(FAIRING)
    assert len(g.board_polygon) >= 2                 # the rim, and at least one hole
    assert len(g.board_polygon[0]) > 100             # a flattened curve, not a rectangle


@needs_parts
def test_a_kicad_mod_reads_with_no_board_at_all():
    from placemat.kicad.read import read_footprint
    fp, digest = read_footprint(_one("*05A20L10P*"))
    assert fp.pads and fp.courtyard_box.width > 0
    assert len(digest) == 64


@needs_parts
def test_the_hold_down_tabs_are_real_pads():
    """The question gaps entry 2026-09-19 answered by grepping: are P_11 and
    P_12 real mechanical pads or symbol pins with nothing behind them."""
    from placemat.kicad.read import read_footprint
    fp, _ = read_footprint(_one("*05A20L10P*"))
    tabs = [p for p in fp.pads if p.number in ("11", "12")]
    assert len(tabs) == 2
    assert all(p.box.width == pytest.approx(2.0, abs=0.01) for p in tabs)


@needs_parts
def test_a_custom_pad_reports_its_copper_and_not_its_anchor():
    """The TPS55288's four corner pads report GetSize() as 0.005 x 0.005."""
    from placemat.kicad.read import read_footprint
    fp, _ = read_footprint(_one("*TPS55288*"))
    odd = [p for p in fp.pads if 0.5 < p.box.width < 1.5 and 0.5 < p.box.height < 1.0]
    assert odd, [(p.number, p.box.width, p.box.height) for p in fp.pads][:6]


@needs_parts
def test_a_standalone_through_pad_reports_no_layers_and_an_smd_pad_reports_one():
    """An empty board has all 32 copper layers enabled, so a through pad read
    with no board would otherwise claim In1..In30 - true of no real board."""
    from placemat.kicad.read import read_footprint
    fp, _ = read_footprint(_one("*TYPE_C*"))
    through = [p for p in fp.pads if p.through]
    smd = [p for p in fp.pads if not p.through]
    assert through and all(p.layers == frozenset() for p in through)
    assert all(len(p.layers) == 1 for p in smd)


@needs_parts
def test_the_digest_tells_two_files_apart():
    from placemat.kicad.read import read_footprint
    a, b = _one("*05A20L10P*"), _one("*TYPE_C*")
    _, da = read_footprint(a)
    _, db = read_footprint(b)
    assert da != db
    assert da == hashlib.sha256(open(a, "rb").read()).hexdigest()


@needs_parts
def test_a_file_pcbnew_cannot_load_says_so(tmp_path):
    from placemat.kicad.read import read_footprint
    bad = tmp_path / "Nonsense.kicad_mod"
    bad.write_text("this is not a footprint")
    with pytest.raises(ValueError) as e:
        read_footprint(bad)
    assert "Nonsense" in str(e.value)
