"""What a run is made from beyond the script itself: the modules the script
imports from beside it, and the files the generator reads for the board.
A change to any of them must show in the run id or refresh the cached
generation."""
import sys
from pathlib import Path

from placemat import runner
from placemat.context import run_script
from placemat.project import BoardSource, generator_inputs, script_fingerprint


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ------------------------------------------------------------ the script's own imports
def test_a_script_imports_a_module_beside_it_without_touching_sys_path(tmp_path):
    _write(tmp_path / "shared_geometry.py", "WIDTH = 42\n")
    script = _write(tmp_path / "Main_layout.py", "import shared_geometry\nRESULT = shared_geometry.WIDTH\n")
    before = list(sys.path)
    module = run_script(script, object())
    assert module.RESULT == 42
    assert sys.path == before
    assert "shared_geometry" not in sys.modules          # the next run imports it afresh


def test_the_fingerprint_changes_with_a_module_the_script_imports(tmp_path):
    shared = _write(tmp_path / "shared_geometry.py", "from helpers import GAP\nWIDTH = 42\n")
    helpers = _write(tmp_path / "helpers.py", "GAP = 1.0\n")
    script = _write(tmp_path / "Main_layout.py", "import shared_geometry\nimport math\n")
    first = script_fingerprint(script)
    shared.write_text("from helpers import GAP\nWIDTH = 43\n")
    second = script_fingerprint(script)
    helpers.write_text("GAP = 2.0\n")                   # imported by the imported module
    third = script_fingerprint(script)
    assert len({first, second, third}) == 3
    assert script_fingerprint(script) == third


# ------------------------------------------------------------ the generator's inputs
def _project(tmp_path):
    root = tmp_path / "electronics"
    _write(root / "pcb.toml", "[workspace]\n")
    board = root / "boards" / "main"
    _write(board / "Main.zen", 'SUB = Module("Sub.zen")\nload("rules.zen", "CONFIG")\n'
                               'Board(name = "Main", layout_path = "layout")\n')
    _write(board / "Sub.zen", 'Layout(name = "Sub", path = "sub")\n')
    _write(board / "rules.zen", "CONFIG = 1\n")
    _write(board / "Other.zen", "X = 1\n")                                  # not loaded by Main
    _write(board / "sub" / "layout.kicad_pcb", "(kicad_pcb sub v1)\n")      # the stamped fragment
    _write(board / "layout" / "layout.kicad_pcb", "(kicad_pcb main)\n")     # the board's own output
    src = BoardSource("Main", board / "Main.zen", board / "layout", board)
    return root, board, src


def test_the_generator_inputs_are_the_zen_it_loads_its_fragments_and_the_workspace(tmp_path):
    root, board, src = _project(tmp_path)
    names = set(generator_inputs(src))
    assert {"Main.zen", "Sub.zen", "rules.zen", "sub/layout.kicad_pcb", "../../pcb.toml"} <= names
    assert "Other.zen" not in names and "layout/layout.kicad_pcb" not in names


def test_a_changed_input_changes_its_digest_and_an_unrelated_file_does_not(tmp_path):
    root, board, src = _project(tmp_path)
    first = generator_inputs(src)
    (board / "Other.zen").write_text("X = 2\n")
    (board / "layout" / "layout.kicad_pcb").write_text("(kicad_pcb main placed)\n")
    assert generator_inputs(src) == first
    (board / "sub" / "layout.kicad_pcb").write_text("(kicad_pcb sub v2)\n")
    changed = generator_inputs(src)
    assert [k for k in changed if changed[k] != first.get(k)] == ["sub/layout.kicad_pcb"]


def test_a_file_named_through_a_symlink_is_an_input_and_a_quoted_name_counts_once_a_file_has_it(tmp_path):
    root, board, src = _project(tmp_path)
    _write(root / "parts" / "R1" / "R1.kicad_mod", "(footprint R1)\n")
    (board / "parts").symlink_to("../../parts")
    (board / "Sub.zen").write_text('Layout(name = "Sub", path = "sub")\n'
                                   'F = "parts/R1/R1.kicad_mod"\nN = "GND"\n')
    names = set(generator_inputs(src))
    assert "../../parts/R1/R1.kicad_mod" in names and "GND" not in names
    _write(board / "GND", "now a file\n")
    assert "GND" in generator_inputs(src)


def _fake_pcb(calls):
    def sh(cmd, cwd, log, timeout, env=None):
        calls.append(cmd)
        out = Path(cwd) / "layout" / "layout.kicad_pcb"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("(kicad_pcb generated %d)\n" % len(calls))
        log.write_text("fake pcb layout\n")
        return 0, 0.1
    return sh


def test_the_cached_generation_is_used_until_an_input_changes(tmp_path, monkeypatch):
    root, board, src = _project(tmp_path)
    calls = []
    monkeypatch.setattr(runner, "_sh", _fake_pcb(calls))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert runner.generate(src, run_dir, fresh=False, quiet=True) is True
    assert runner.generate(src, run_dir, fresh=False, quiet=True) is False      # restored
    assert len(calls) == 1
    (board / "Sub.zen").write_text('Layout(name = "Sub", path = "sub")\nR = 1\n')
    assert runner.generate(src, run_dir, fresh=False, quiet=True) is True
    assert len(calls) == 2
    assert "Sub.zen" in (run_dir / "generate.log").read_text()
    assert runner.generate(src, run_dir, fresh=False, quiet=True) is False


def test_a_cache_with_no_record_of_its_inputs_is_generated_again(tmp_path, monkeypatch):
    root, board, src = _project(tmp_path)
    calls = []
    monkeypatch.setattr(runner, "_sh", _fake_pcb(calls))
    cache = runner.cached_generation(src)
    _write(cache / "layout.kicad_pcb", "(kicad_pcb from an older placemat)\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert runner.generate(src, run_dir, fresh=False, quiet=True) is True
    assert len(calls) == 1


def test_the_generate_arguments_are_an_input(tmp_path):
    root, board, src = _project(tmp_path)
    import dataclasses
    other = dataclasses.replace(src, generate_args=("--config", "style=side"))
    assert generator_inputs(src) != generator_inputs(other)


def test_a_project_the_generator_writes_is_not_an_input(tmp_path):
    root, board, src = _project(tmp_path)
    zen = board / "Main.zen"
    zen.write_text(zen.read_text() + 'Project(name = "Main", path = "kicad/Main.kicad_pro", schematic = True, layout = False)\n'
                   'Project(name = "Sub", path = "kicad", schematic = True, layout = False)\n')
    _write(board / "kicad" / "Main.kicad_pro", "{}\n")
    _write(board / "kicad" / "sub.kicad_sch", "(kicad_sch)\n")
    assert not [k for k in generator_inputs(src) if k.startswith("kicad/")]


def test_the_fingerprint_changes_with_the_script_s_lock(tmp_path):
    """The lock decides placements, so accepting and running again is a
    different run."""
    script = _write(tmp_path / "Main_layout.py", "X = 1\n")
    without = script_fingerprint(script)
    _write(tmp_path / "Main_layout.lock.json", '{"format": 1, "entries": []}\n')
    assert script_fingerprint(script) != without


def test_a_file_placemat_did_not_write_survives_a_restore_and_a_regeneration(tmp_path, monkeypatch):
    """A hand layout saved into the layout folder was deleted by the next run."""
    root, board, src = _project(tmp_path)
    calls = []
    monkeypatch.setattr(runner, "_sh", _fake_pcb(calls))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert runner.generate(src, run_dir, fresh=False, quiet=True) is True
    hand = src.layout_dir / "layout_hand.kicad_pcb"
    hand.write_text("(kicad_pcb by hand)\n")
    assert runner.generate(src, run_dir, fresh=False, quiet=True) is False          # restored from the cache
    assert hand.read_text() == "(kicad_pcb by hand)\n"
    assert runner.generate(src, run_dir, fresh=True, quiet=True) is True            # generated again
    assert hand.read_text() == "(kicad_pcb by hand)\n"
    assert "layout_hand.kicad_pcb" in (run_dir / "generate.log").read_text()


def test_a_board_edited_since_its_last_run_is_kept(tmp_path, monkeypatch):
    from placemat.report import RunRecord, record_latest
    root, board, src = _project(tmp_path)
    calls = []
    monkeypatch.setattr(runner, "_sh", _fake_pcb(calls))
    runs = src.board_dir / ".placemat" / "runs"
    last = runs / "last"
    last.mkdir(parents=True)
    (last / "layout.kicad_pcb").write_text("(kicad_pcb as placemat wrote it)\n")
    rec = RunRecord(run_id="last", board=src.name, status="ok", paths={"run_dir": str(last)})
    record_latest(runs, rec.save(last / "run.json"), src.name)
    src.layout_dir.mkdir(parents=True, exist_ok=True)
    src.pcb.write_text("(kicad_pcb moved by hand in KiCad)\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    runner.generate(src, run_dir, fresh=True, quiet=True)
    assert (run_dir / "kept" / "layout.kicad_pcb").read_text() == "(kicad_pcb moved by hand in KiCad)\n"


def test_a_run_that_does_not_render_keeps_the_last_renders(tmp_path, monkeypatch):
    """--no-render skips making new renders; it does not delete the old ones.
    A run that renders replaces them, so it does not carry them over."""
    root, board, src = _project(tmp_path)
    calls = []
    monkeypatch.setattr(runner, "_sh", _fake_pcb(calls))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert runner.generate(src, run_dir, fresh=False, quiet=True) is True
    renders = [src.layout_dir / n for n in ("layout.png", "layout-iso.png")]
    for p in renders:
        p.write_bytes(b"png of the last run")
    assert runner.generate(src, run_dir, fresh=False, quiet=True, keep_renders=True) is False   # restored
    assert all(p.read_bytes() == b"png of the last run" for p in renders)
    assert runner.generate(src, run_dir, fresh=True, quiet=True, keep_renders=True) is True     # generated again
    assert all(p.read_bytes() == b"png of the last run" for p in renders)
    assert runner.generate(src, run_dir, fresh=False, quiet=True) is False                       # a run that renders
    assert not any(p.exists() for p in renders)


def test_the_generation_environment_drops_the_kicad_project_variable(monkeypatch):
    """pcbnew leaves KIPRJMOD set in a process that saved a board; pcb layout keeps a set value instead of using the board's folder."""
    monkeypatch.setenv("KIPRJMOD", "")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("PLACEMAT_KEEP", "1")
    env = runner.generation_env()
    assert "KIPRJMOD" not in env and "DISPLAY" not in env and env["PLACEMAT_KEEP"] == "1"


def test_a_run_folder_keeps_the_boards_rules_beside_its_copy(tmp_path):
    from placemat.runner import copy_board
    board = tmp_path / "layout"
    board.mkdir()
    (board / "layout.kicad_pcb").write_text("pcb")
    (board / "layout.kicad_pro").write_text("pro")
    (board / "layout.kicad_dru").write_text("dru")
    run = tmp_path / "run"
    run.mkdir()
    copy_board(board / "layout.kicad_pcb", run)
    assert sorted(p.name for p in run.iterdir()) == ["layout.kicad_dru", "layout.kicad_pcb", "layout.kicad_pro"]
    assert (run / "layout.kicad_dru").read_text() == "dru"


def test_a_board_with_no_rules_beside_it_names_what_is_missing(tmp_path):
    from placemat.runner import missing_rules
    (tmp_path / "b.kicad_pcb").write_text("pcb")
    assert missing_rules(tmp_path / "b.kicad_pcb") == [".kicad_pro", ".kicad_dru"]
    (tmp_path / "b.kicad_pro").write_text("pro")
    (tmp_path / "b.kicad_dru").write_text("dru")
    assert missing_rules(tmp_path / "b.kicad_pcb") == []


def test_a_generation_is_current_right_after_it_is_made_and_stale_once_a_stamped_layout_is_written_again(tmp_path, monkeypatch):
    """The record of what a generation was made from is taken by the generation itself: a module's layout written by placemat
    after it is a change, one written before it is not."""
    root, board, src = _project(tmp_path)
    monkeypatch.setattr(runner, "_sh", _fake_pcb([]))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    assert runner.stale_record(src) == {"form": "no_record"}
    runner.generate(src, run_dir, fresh=False, quiet=True)
    assert runner.stale_record(src) is None
    (board / "sub" / "layout.kicad_pcb").write_text("(kicad_pcb sub as a run of the module placed it)\n")
    assert runner.stale_record(src) == {"form": "changed", "files": ["sub/layout.kicad_pcb"]}
    assert runner.stale_text(runner.stale_record(src)) == "sub/layout.kicad_pcb changed since it was generated"
    runner.generate(src, run_dir, fresh=False, quiet=True)
    assert runner.stale_record(src) is None
    (board / "sub" / "layout.kicad_pcb").write_text("(kicad_pcb sub as a run of the module placed it)\n")      # the same bytes again
    assert runner.stale_record(src) is None
