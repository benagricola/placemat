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
