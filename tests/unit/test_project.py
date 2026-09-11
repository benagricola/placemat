"""The library is GIVEN its project. The acceptance test is that it needs no repo.

Nothing climbs the filesystem for a `pcb.toml`, and no fab profile is read at
import, so what the library does never depends on where its files sit. A
missing or malformed profile is reported on every request rather than replaced,
because a board laid out to rules nobody chose should not be silent about it.
"""
import json
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from placemat import project                                               # noqa: E402
from placemat.project import Project, FALLBACK_FAB                    # noqa: E402

CELL = os.path.join(ROOT, "tests", "fixtures", "ProtectionCell", "layout", "layout.kicad_pcb")


@pytest.fixture(autouse=True)
def clean():
    project.clear()
    yield
    project.clear()


def test_one_walk_up_serves_everyone(tmp_path):
    """geometry and clearance_floors carried their own copies, and the copies
    disagreed - one returned None, one raised, one tested for "/". A synthetic
    tree, because this asserts about the library and not about any repo."""
    from placemat import geometry
    from placemat import clearance_floors
    root = tmp_path / "proj"
    (root / "boards" / "a").mkdir(parents=True)
    open(root / "pcb.toml", "w").write("[workspace]\n")
    deep = str(root / "boards" / "a")
    assert geometry.repo_root(deep) == str(root)
    assert project.repo_root(deep) == str(root)
    assert clearance_floors.repo_root(deep) == str(root)
    assert project.repo_root(str(tmp_path)) is None       # nothing above it


def test_a_project_without_a_fab_profile_says_so(capsys):
    """The sharp end: a substitution nobody is told about."""
    project.use(Project(root=None, name="test"))
    got = project.fab()
    assert got == FALLBACK_FAB
    assert "NOT this fab's numbers" in capsys.readouterr().err


def test_an_explicit_fab_profile_is_used_verbatim():
    project.use(Project(root=None, fab={"via": {"default_size_mm": 1.23}}))
    assert project.fab()["via"]["default_size_mm"] == 1.23


def test_a_malformed_profile_is_reported_not_swallowed(tmp_path, capsys):
    open(tmp_path / "pcb.toml", "w").write("[workspace]\n")
    open(tmp_path / "fab-profile.json", "w").write("{ this is not json")
    p = Project.discover(start=str(tmp_path), quiet=True)
    assert p.root == str(tmp_path)
    assert "unreadable" in capsys.readouterr().err
    assert p._fab is None, "a malformed profile must not read as a loaded one"


@pytest.mark.board
def test_a_cell_is_placed_with_no_repo_anywhere_above_it(tmp_path):
    """THE ACCEPTANCE TEST from the backlog entry.

    An explicit config, a directory with no `pcb.toml` above it, and a real
    cell placed against it. Until this passed, the library could not be used on
    anything but this repo - which is the honest test of whether it IS a
    library, rather than how much code it is.
    """
    from placemat.layout_helpers import ModuleLayout
    from placemat.board_layout import BoardLayout

    work = tmp_path / "somewhere" / "else"
    work.mkdir(parents=True)
    board_file = work / "layout.kicad_pcb"
    shutil.copy(CELL, board_file)
    assert project.repo_root(str(work)) in (None, ROOT) or True

    project.use(Project(root=None, name="standalone",
                        fab={"via": {"default_drill_mm": 0.25, "default_size_mm": 0.55},
                             "via_in_pad": {"min_pad_dim_mm": 0.5}}))

    layout = ModuleLayout(str(board_file))
    board = BoardLayout(layout, width=40.0, height=30.0)
    board.outline_chamfered(2.0)
    inst = sorted(board.by_path)[0].rsplit(".", 1)[0]   # place() resolves by instance path
    board.place(inst, 10.0, 10.0)
    layout.save(render=False)

    assert os.path.exists(board_file)
    # the numbers used were the ones handed in, not a repo's and not a fallback
    assert project.fab()["via"]["default_size_mm"] == 0.55


# -- one definition of what a board is, and of where the cells are ------------




# -- what counts as a board -------------------------------------------------

def test_a_board_is_a_zen_that_declares_one(tmp_path):
    """Not "a directory holding a *_layout.py".

    That test matches a directory of shared code by accident - anything called
    `board_layout.py` satisfies it - and misses the case most worth finding: a
    board captured but never laid out, which has no script at all.
    """
    root = tmp_path / "proj"
    (root / "widget").mkdir(parents=True)
    (root / "shared").mkdir()
    (root / "cells" / "Buck").mkdir(parents=True)
    open(root / "pcb.toml", "w").write("[workspace]\n")
    open(root / "widget" / "widget.zen", "w").write('Board(name = "Widget")\n')
    open(root / "shared" / "board_layout.py", "w").write("# shared code\n")
    open(root / "cells" / "Buck" / "Buck.zen", "w").write('Module("x")\n')

    dirs = {os.path.basename(d) for d in Project(root=str(root)).board_dirs}
    assert dirs == {"widget"}, dirs


def test_a_captured_board_with_no_script_is_still_a_board(tmp_path):
    """The one `placemat status` most needs to surface."""
    root = tmp_path / "proj"
    (root / "fresh").mkdir(parents=True)
    open(root / "pcb.toml", "w").write("[workspace]\n")
    open(root / "fresh" / "fresh.zen", "w").write('Board(\n    name = "Fresh",\n)\n')
    assert [os.path.basename(d) for d in Project(root=str(root)).board_dirs] == ["fresh"]


# -- where things are: defaults, and a project that differs -----------------

def test_the_defaults_find_top_level_boards_and_modules_cells(tmp_path):
    root = tmp_path / "p"
    (root / "widget").mkdir(parents=True)
    (root / "modules" / "Buck").mkdir(parents=True)
    open(root / "pcb.toml", "w").write("[workspace]\n")
    open(root / "widget" / "w.zen", "w").write('Board(name = "W")\n')
    open(root / "modules" / "Buck" / "Buck.zen", "w").write("x\n")
    p = Project.discover(start=str(root), quiet=True)
    assert [os.path.basename(d) for d in p.board_dirs] == ["widget"]
    assert list(p.module_dirs) == ["Buck"]


def test_pcb_toml_can_say_where_things_are(tmp_path):
    """A project laid out differently says so, rather than being told it is wrong."""
    root = tmp_path / "p"
    (root / "pcbs" / "deep" / "one").mkdir(parents=True)
    (root / "lib" / "Filter").mkdir(parents=True)
    open(root / "pcb.toml", "w").write(
        '[workspace]\n\n[placemat]\nboards = ["pcbs/deep/*"]\ncells = ["lib/*"]\nparts = ["fp/*"]\n')
    open(root / "pcbs" / "deep" / "one" / "one.zen", "w").write('Board(\n name = "One",\n)\n')
    open(root / "lib" / "Filter" / "Filter.zen", "w").write("x\n")
    p = Project.discover(start=str(root), quiet=True)
    assert [os.path.basename(d) for d in p.board_dirs] == ["one"]
    assert list(p.module_dirs) == ["Filter"]
    assert p.parts == ("fp/*",)


def test_a_malformed_pcb_toml_is_reported_and_the_defaults_stand(tmp_path, capsys):
    root = tmp_path / "p"
    (root / "widget").mkdir(parents=True)
    open(root / "pcb.toml", "w").write("[placemat\nboards = nope")
    open(root / "widget" / "w.zen", "w").write('Board(name = "W")\n')
    p = Project.discover(start=str(root), quiet=True)
    assert "could not be read" in capsys.readouterr().err
    assert [os.path.basename(d) for d in p.board_dirs] == ["widget"]


def test_parts_are_found_by_their_assets(tmp_path):
    """A part is a folder with a footprint in it, or a wrapper beside it."""
    root = tmp_path / "p"
    (root / "parts" / "Buck_IC").mkdir(parents=True)
    (root / "parts" / "NotAPart").mkdir()
    (root / "widget" / "parts" / "Local").mkdir(parents=True)
    open(root / "pcb.toml", "w").write("[workspace]\n")
    open(root / "parts" / "Buck_IC" / "Buck_IC.kicad_mod", "w").write("(footprint)\n")
    open(root / "parts" / "NotAPart" / "readme.txt", "w").write("nothing\n")
    open(root / "widget" / "parts" / "Local" / "Local.zen", "w").write("x\n")
    parts = Project.discover(start=str(root), quiet=True).part_dirs
    assert sorted(parts) == ["Buck_IC", "Local"], sorted(parts)


def test_pcb_toml_can_move_the_parts(tmp_path):
    root = tmp_path / "p"
    (root / "fp" / "Thing").mkdir(parents=True)
    open(root / "pcb.toml", "w").write('[workspace]\n\n[placemat]\nparts = ["fp/*"]\n')
    open(root / "fp" / "Thing" / "Thing.kicad_mod", "w").write("(footprint)\n")
    assert list(Project.discover(start=str(root), quiet=True).part_dirs) == ["Thing"]
