"""A script names its board by sitting beside the .zen that declares it."""
from pathlib import Path

import pytest

from placemat.project import BoardSource, find_board, fab_profile


def test_the_zen_beside_the_script_declares_the_board(tmp_path):
    (tmp_path / "widget.zen").write_text(
        'X = Module("parts/X.zen")\nBoard(\n    name = "Widget",\n    layout_path = "layout/Widget",\n    layers = 2,\n)\n')
    (tmp_path / "Widget_layout.py").write_text("")
    src = find_board(tmp_path / "Widget_layout.py")
    assert src == BoardSource(name="Widget", zen=tmp_path / "widget.zen", layout_dir=tmp_path / "layout/Widget",
                              board_dir=tmp_path)


def test_a_directory_without_a_board_zen_is_an_error(tmp_path):
    (tmp_path / "not_a_board.zen").write_text("X = Module('x')\n")
    (tmp_path / "s.py").write_text("")
    with pytest.raises(FileNotFoundError):
        find_board(tmp_path / "s.py")


def test_the_fab_profile_is_found_walking_up_and_has_defaults(tmp_path):
    board = tmp_path / "boards" / "w"
    board.mkdir(parents=True)
    (tmp_path / "fab-profile.json").write_text('{"via": {"default_drill_mm": 0.25, "default_size_mm": 0.5}}')
    fab = fab_profile(board)
    assert fab.via_drill == 0.25 and fab.via_size == 0.5
    assert fab.courtyard_excess == 0.10                     # default when the file does not say
    assert fab_profile(Path("/")).via_drill == 0.3          # no file at all: defaults
