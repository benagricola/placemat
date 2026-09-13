"""Copper ops written through pcbnew come back in the snapshot, and DRC on the
result is readable as numbers."""
import shutil

from placemat.layout import Board
from placemat.kicad.drc import run_drc
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.values import CopperLayer, Location, Net, Part, PadRef
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]


def _copy(breakout_pcb, tmp_path):
    for ext in (".kicad_pcb", ".kicad_pro"):
        src = breakout_pcb.with_suffix(ext)
        if src.exists():
            shutil.copy(src, tmp_path / ("layout" + ext))
    return tmp_path / "layout.kicad_pcb"


def test_tracks_vias_pours_and_a_plane_round_trip(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    before = read_board(pcb)
    b = Board(before, edge_margin=0.0)
    b.size(width=before.outline_box.width, height=before.outline_box.height, chamfer=2.0)
    b.track(Net("TERM_MID"), [PadRef(Part("term_ra"), "TERM_MID"), PadRef(Part("term_rb"), "TERM_MID")],
            layer=CopperLayer.F, width=0.3)
    b.via(Net("GND"), Location(5.0, 100.0))
    b.pour(Net("V48P"), [Location(50, 100), Location(60, 100), Location(60, 105), Location(50, 105)],
           layer=CopperLayer.F)
    b.plane(Net("GND"), layers=(CopperLayer.B,), inset=0.4, chamfer=2.0)
    plan = b.resolve()
    apply_plan(pcb, plan)
    after = read_board(pcb)
    n_tracks = len([c for c in after.copper if c.kind == "track"])
    n_vias = len([c for c in after.copper if c.kind == "via"])
    assert n_tracks == len([c for c in before.copper if c.kind == "track"]) + 1
    assert n_vias == len([c for c in before.copper if c.kind == "via"]) + 1
    assert any(c.kind == "poly" and c.net == "V48P" and abs(c.box.left - 50.0) <= 0.11 for c in after.copper)   # the 0.2 stroke rounds the outline outward
    zones = [c for c in after.copper if c.kind == "zone"]
    assert zones and zones[0].net == "GND" and CopperLayer.B in zones[0].layers
    assert zones[0].box.width > 100     # filled, not an empty outline


def test_drc_on_the_committed_board_reads_as_numbers(breakout_pcb, tmp_path):
    pcb = _copy(breakout_pcb, tmp_path)
    report = run_drc(pcb, tmp_path / "drc.json")
    assert report.real == {}                       # the committed board is DRC clean
    assert report.unconnected == 0
    assert set(report.outstanding) <= {"via_dangling", "track_dangling", "isolated_copper"}
    assert report.violations >= 0 and report.path.exists()
