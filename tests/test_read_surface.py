"""The read surface against real boards: the standalone footprint reader, the
board's true outline, and the promise that this reader and the placer's agree."""
import pytest

pytest.importorskip("pcbnew")        # the module imports placemat.kicad, which needs KiCad's pcbnew

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


@needs_parts
def test_measure_reads_a_kicad_mod_from_the_command_line(capsys):
    import argparse
    from placemat import cli
    args = argparse.Namespace(pcb=_one("*05A20L10P*"), items=[], pads=True, json=False)
    assert cli.cmd_measure(args) == 0
    out = capsys.readouterr().out
    assert "pad" in out and "sha256" in out and "courtyard" in out


@needs_breakout
def test_measure_on_a_board_prints_position_and_boxes(breakout_pcb, capsys):
    import argparse
    from placemat import cli
    g = read_board(breakout_pcb)
    args = argparse.Namespace(pcb=str(breakout_pcb), items=[g.footprints[0].inst],
                              pads=False, json=False)
    assert cli.cmd_measure(args) == 0
    out = capsys.readouterr().out
    for word in ("body", "courtyard", "physical", "origin"):
        assert word in out, word


@needs_breakout
def test_measure_json_carries_the_same_numbers(breakout_pcb, capsys):
    import argparse
    import json as _json
    from placemat import cli
    g = read_board(breakout_pcb)
    fp = g.footprints[0]
    args = argparse.Namespace(pcb=str(breakout_pcb), items=[fp.inst], pads=True, json=True)
    assert cli.cmd_measure(args) == 0
    doc = _json.loads(capsys.readouterr().out)
    (one,) = doc["parts"]
    assert one["ref"] == fp.ref
    assert one["body"] == [round(fp.body_box.width, 3), round(fp.body_box.height, 3)]
    assert len(one["pads"]) == len(fp.pads)
    assert "copper_on_pads" in one


@needs_breakout
def test_the_measured_pad_centres_are_the_placer_s_pad_locations(breakout_pcb):
    """Two readers of the same board must agree, or a script and a review of
    that script are measuring different things."""
    from placemat import describe
    from placemat.occupancy import Occupancy
    g = read_board(breakout_pcb)
    occ = Occupancy(g, edge_margin=0.0)
    fp = [f for f in g.footprints if len(f.pads) >= 3][0]
    for p in fp.pads:
        said = describe.pad_facts(fp, p, g)["at"]
        placed = occ.pad_location(fp.ref, p.number)
        assert said == [pytest.approx(placed.x, abs=1e-6), pytest.approx(placed.y, abs=1e-6)]


@needs_breakout
def test_an_unknown_item_says_what_the_parts_are_called(breakout_pcb):
    import argparse
    from placemat import cli
    args = argparse.Namespace(pcb=str(breakout_pcb), items=["no_such_part"], pads=False, json=False)
    with pytest.raises(SystemExit) as e:
        cli.cmd_measure(args)
    assert "no_such_part" in str(e.value) and "placemat parts" in str(e.value)


@needs_breakout
def test_measure_with_no_items_still_lists_the_cells(breakout_pcb, capsys):
    """The old behaviour, unchanged: this is purely additive."""
    import argparse
    from placemat import cli
    args = argparse.Namespace(pcb=str(breakout_pcb), items=[], pads=False, json=False)
    assert cli.cmd_measure(args) == 0
    out = capsys.readouterr().out
    assert "cell " in out and "members" in out


@needs_breakout
def test_parts_lists_every_footprint_with_its_area_and_pins(breakout_pcb, capsys):
    import argparse
    from placemat import cli
    args = argparse.Namespace(pcb=str(breakout_pcb), json=False)
    assert cli.cmd_parts(args) == 0
    out = capsys.readouterr().out
    g = read_board(breakout_pcb)
    assert "instance" in out and "pins" in out and "mm2" in out
    assert out.count("\n") >= len(g.footprints)


@needs_breakout
def test_parts_json_is_one_row_per_footprint(breakout_pcb, capsys):
    import argparse
    import json as _json
    from placemat import cli
    args = argparse.Namespace(pcb=str(breakout_pcb), json=True)
    assert cli.cmd_parts(args) == 0
    doc = _json.loads(capsys.readouterr().out)
    g = read_board(breakout_pcb)
    assert len(doc["parts"]) == len(g.footprints)
    assert {r["ref"] for r in doc["parts"]} == {fp.ref for fp in g.footprints}


@needs_breakout
def test_a_placed_pad_reports_only_layers_the_board_has(breakout_pcb):
    """A through pad's own layer set is every copper layer KiCad can name,
    whatever board it sits on, so a 2-layer board was reporting pads on
    In1.Cu through In30.Cu. What a pad reports is the board's own stackup."""
    g = read_board(breakout_pcb)
    stack = set(g.layers)
    pads = [p for fp in g.footprints for p in fp.pads]
    through = [p for p in pads if p.through]
    assert through, "the breakout has no through-hole pads to check"
    assert all(set(p.layers) <= stack for p in pads)
    assert all(set(p.layers) == stack for p in through)


@needs_fairing
def test_a_four_layer_boards_pads_name_four_layers():
    g = read_board(FAIRING)
    assert len(g.layers) == 4
    through = [p for fp in g.footprints for p in fp.pads if p.through]
    assert through and all(len(p.layers) == 4 for p in through)
