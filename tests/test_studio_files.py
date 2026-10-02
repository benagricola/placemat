"""The files a studio watches: what script_fingerprint reads, named."""
from pathlib import Path

from placemat.project import script_files, script_fingerprint


def _tree(tmp_path):
    root = tmp_path / "board"
    (root / "modules" / "m").mkdir(parents=True)
    (root / "placemat.toml").write_text("")
    (root / "shared.py").write_text("X = 1\n")
    (root / "modules" / "m" / "helper.py").write_text("import shared\nY = shared.X\n")
    script = root / "modules" / "m" / "M_layout.py"
    script.write_text("import helper\nfrom context import board\n")
    return root, script


def test_script_files_are_the_script_its_imports_and_what_a_run_reads_beside_it(tmp_path):
    root, script = _tree(tmp_path)
    script.with_name("M_layout.lock.json").write_text("{}")
    script.with_name("M_layout.routes.json").write_text("{}")
    names = [Path(p).name for p in script_files(script)]
    assert names == ["M_layout.py", "helper.py", "shared.py", "M_layout.lock.json", "M_layout.routes.json"]


def test_a_lock_that_does_not_exist_yet_is_still_named(tmp_path):
    root, script = _tree(tmp_path)
    files = script_files(script, missing=True)
    assert script.with_name("M_layout.lock.json") in files
    assert script.with_name("M_layout.lock.json") not in script_files(script)


def test_the_fingerprint_is_built_from_the_same_files(tmp_path):
    root, script = _tree(tmp_path)
    text = script_fingerprint(script)
    for name in ("X = 1", "import shared", "import helper"):
        assert name in text
    script.with_name("M_layout.lock.json").write_text('{"a": 1}')
    assert script_fingerprint(script).endswith('lock\0{"a": 1}')
