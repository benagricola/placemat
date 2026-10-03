"""route_spread's order and jitter runs route the board file as given: a
save through KiCad reorders and reformats it, and the router's result
can depend on that, so a spread of re-saved boards measures a different
board from the one routed elsewhere."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
import route_spread  # noqa: E402


def test_an_order_or_jitter_run_routes_the_board_byte_for_byte(tmp_path):
    board = tmp_path / "b.kicad_pcb"
    board.write_text("(kicad_pcb (version 20241229) (generator \"hand\"))\n")
    got = route_spread.copied(board, tmp_path / "run00")
    assert got.read_bytes() == board.read_bytes()
    assert not (tmp_path / "run00" / "in.kicad_pro").exists()     # none beside it: none written


def test_its_project_comes_with_it(tmp_path):
    board = tmp_path / "b.kicad_pcb"
    board.write_text("(kicad_pcb)\n")
    (tmp_path / "b.kicad_pro").write_text("{}\n")
    route_spread.copied(board, tmp_path / "run00")
    assert (tmp_path / "run00" / "in.kicad_pro").read_text() == "{}\n"


def test_disconnected_reads_the_open_nets_from_kicads_drc(tmp_path):
    import shutil

    import pytest
    pcbnew = pytest.importorskip("pcbnew")
    from placemat.kicad.drc import run_drc  # noqa: F401
    src = Path(__file__).resolve().parents[1] / "fixtures/fairing/modules/ringsensor/layout/layout"
    for ext in (".kicad_pcb", ".kicad_pro"):
        shutil.copy(str(src) + ext, tmp_path / ("b" + ext))
    board = tmp_path / "b.kicad_pcb"
    assert route_spread.disconnected(board) == []              # routed as it stands
    brd = pcbnew.LoadBoard(str(board))
    for t in list(brd.GetTracks()):
        brd.Delete(t)
    brd.Save(str(board))
    assert route_spread.disconnected(board)                    # a list of net names
