"""Which words on a command line are BOARDS, and which are left alone.

`placemat airwires middleweight --json out.json` names one board and one file.
Argparse decides which is which, because it is the only thing that knows
`--json` takes a value - a rule based on position breaks `placemat polys
--allow-ground middleweight`, where the word after a flag IS the board.

These test the argument TYPES the commands share.
"""
import argparse
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from placemat import args as A                                # noqa: E402
from placemat import project                                  # noqa: E402
from placemat.project import Project                          # noqa: E402


@pytest.fixture(autouse=True)
def a_project(tmp_path):
    """One generated board, one captured but never placed, one cell."""
    root = tmp_path / "p"
    (root / "widget" / "layout" / "Widget").mkdir(parents=True)
    (root / "fresh").mkdir(parents=True)
    (root / "modules" / "Buck").mkdir(parents=True)
    open(root / "pcb.toml", "w").write("[workspace]\n")
    open(root / "widget" / "widget.zen", "w").write('Board(name = "Widget")\n')
    open(root / "widget" / "Widget_layout.py", "w").write("# script\n")
    open(root / "widget" / "layout" / "Widget" / "layout.kicad_pcb", "w").write("(kicad_pcb)\n")
    open(root / "fresh" / "fresh.zen", "w").write('Board(name = "Fresh")\n')
    open(root / "modules" / "Buck" / "Buck.zen", "w").write("x\n")
    (root / "modules" / "Buck" / "layout").mkdir()
    open(root / "modules" / "Buck" / "layout" / "layout.kicad_pcb", "w").write("(kicad_pcb)\n")
    project.use(Project.discover(start=str(root), quiet=True))
    yield root
    project.clear()


def test_a_board_name_becomes_its_layout():
    assert A.board("widget").endswith("/widget/layout/Widget/layout.kicad_pcb")


def test_a_path_is_taken_as_given(a_project):
    p = str(a_project / "modules" / "Buck" / "layout" / "layout.kicad_pcb")
    assert A.board(p) == p


def test_a_board_never_generated_says_so():
    with pytest.raises(argparse.ArgumentTypeError) as e:
        A.board("fresh")
    assert "never been generated" in str(e.value)


def test_a_word_that_is_no_board_lists_the_boards():
    with pytest.raises(argparse.ArgumentTypeError) as e:
        A.board("wibble")
    assert "neither a file nor a board" in str(e.value) and "widget" in str(e.value)


def test_a_board_name_finds_its_script():
    assert A.script("widget").endswith("Widget_layout.py")


def test_a_cell_name_finds_its_fragment():
    assert A.cell("Buck").endswith("/modules/Buck/layout/layout.kicad_pcb")


def test_a_board_is_not_a_cell():
    with pytest.raises(argparse.ArgumentTypeError) as e:
        A.cell("widget")
    assert "not a cell here" in str(e.value)


def test_a_board_name_finds_its_zen():
    assert A.zen("widget").endswith("widget.zen")


def test_argparse_owns_which_word_is_which():
    """The case a positional rule gets wrong: a switch, then the board."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-ground", action="store_true")
    ap.add_argument("--json", nargs="?", const="-")
    ap.add_argument("pcb", type=A.board)
    ns = ap.parse_args(["--allow-ground", "widget", "--json", "out.json"])
    assert ns.pcb.endswith("layout.kicad_pcb")
    assert ns.json == "out.json", "an option's value must not be resolved as a board"


# -- --json replaces the summary, it does not accompany it ------------------

def test_emit_writes_to_stdout_for_a_bare_flag(capsys):
    from placemat.report import emit
    assert emit({"a": 1}, "-") is True
    assert json.loads(capsys.readouterr().out) == {"a": 1}


def test_emit_writes_a_file_and_says_so_on_stderr(tmp_path, capsys):
    from placemat.report import emit
    out = tmp_path / "m.json"
    assert emit({"a": 1}, str(out)) is True
    cap = capsys.readouterr()
    assert cap.out == "", "a file destination must not also print to stdout"
    assert "wrote" in cap.err, "the confirmation belongs on stderr, clear of a pipe"
    assert json.loads(out.read_text()) == {"a": 1}


def test_emit_does_nothing_without_the_flag(capsys):
    from placemat.report import emit
    assert emit({"a": 1}, None) is False
    assert capsys.readouterr().out == ""


def test_hush_holds_the_summary_and_unhush_gives_stdout_back(capsys):
    """It holds stdout itself, so printing from anywhere the gate calls is held."""
    from placemat.report import hush, unhush

    def deep():
        print("summary from a helper")

    saved = hush("out.json")
    deep()
    unhush(saved)
    print("after")
    out = capsys.readouterr().out
    assert "summary from a helper" not in out
    assert "after" in out


def test_hush_is_a_no_op_without_the_flag(capsys):
    from placemat.report import hush, unhush
    saved = hush(None)
    print("kept")
    unhush(saved)
    assert "kept" in capsys.readouterr().out


def test_a_directory_with_two_boards_picks_the_one_named_after_it(tmp_path):
    """A daughter board or a variant sits beside its parent.

    Taking the first alphabetically lays out the wrong one and says nothing -
    and `middleweight-encoder.zen` sorts before `middleweight.zen`, so the
    wrong one is what you get.
    """
    root = tmp_path / "two"
    (root / "widget").mkdir(parents=True)
    open(root / "pcb.toml", "w").write("[workspace]\n")
    open(root / "widget" / "widget.zen", "w").write('Board(name = "Widget")\n')
    open(root / "widget" / "widget-daughter.zen", "w").write('Board(name = "Daughter")\n')
    open(root / "widget" / "Widget_layout.py", "w").write("#\n")
    open(root / "widget" / "WidgetDaughter_layout.py", "w").write("#\n")
    project.use(Project.discover(start=str(root), quiet=True))
    assert A.zen("widget").endswith("widget.zen")
    assert A.script("widget").endswith("Widget_layout.py")


def test_two_candidates_and_neither_is_the_board_asks_which(tmp_path):
    root = tmp_path / "amb"
    (root / "widget").mkdir(parents=True)
    open(root / "pcb.toml", "w").write("[workspace]\n")
    open(root / "widget" / "one.zen", "w").write('Board(name = "One")\n')
    open(root / "widget" / "two.zen", "w").write('Board(name = "Two")\n')
    project.use(Project.discover(start=str(root), quiet=True))
    with pytest.raises(argparse.ArgumentTypeError) as e:
        A.zen("widget")
    assert "name the one you mean" in str(e.value)
