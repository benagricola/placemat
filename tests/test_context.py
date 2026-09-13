"""`from placemat import board` inside a script talks to whatever Board the
runner bound; outside a run it says so instead of failing obscurely."""
import pytest

from placemat import board as board_proxy
from placemat.layout import Board
from placemat.context import bind, unbind, run_script
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


def test_the_proxy_forwards_to_the_bound_board():
    real = Board(board_geometry([footprint("R1", 10, 10, inst="r1")]), edge_margin=1.0)
    with bind(real):
        board_proxy.place(Part("r1"), at=Location(5, 5))
    assert real.resolve().placement("r1").location == Location(5, 5)


def test_the_proxy_refuses_outside_a_run():
    unbind()
    with pytest.raises(RuntimeError):
        board_proxy.place(Part("r1"), at=Location(5, 5))


def test_run_script_executes_a_file_against_a_board(tmp_path):
    script = tmp_path / "s.py"
    script.write_text("from placemat import board, Part, Location\n"
                      "board.size(width=40, height=40)\n"
                      "board.place(Part('r1'), at=Location(7, 7))\n")
    real = Board(board_geometry([footprint("R1", 10, 10, inst="r1")]), edge_margin=1.0)
    run_script(script, real)
    plan = real.resolve()
    assert plan.outline.width == 40 and plan.placement("r1").location == Location(7, 7)


def test_a_script_error_names_the_script_line(tmp_path):
    script = tmp_path / "bad.py"
    script.write_text("from placemat import board, Part, Location\n\nboard.place(Part('nope'), at=Location(1, 1))\n")
    real = Board(board_geometry([footprint("R1", 10, 10, inst="r1")]), edge_margin=1.0)
    with pytest.raises(KeyError) as e:
        run_script(script, real)
    assert "nope" in str(e.value)
