"""A layout script in a module's own folder imports shared helpers from the
folders above it, up to the one holding the nearest placemat.toml; what it
imported from them is dropped after the run, so a rerun reads them again."""
import sys

from placemat.context import run_script


def _tree(tmp_path, value):
    root = tmp_path / "boards" / "core"
    (root / "modules" / "usb").mkdir(parents=True)
    (root / "placemat.toml").write_text("")
    (root / "shared_frame.py").write_text("VALUE = %d\n" % value)
    script = root / "modules" / "usb" / "Usb_layout.py"
    script.write_text("from shared_frame import VALUE\nSEEN = VALUE\n")
    return root, script


def test_a_script_imports_a_helper_from_the_folder_holding_placemat_toml(tmp_path):
    root, script = _tree(tmp_path, 1)
    assert run_script(script, object()).SEEN == 1
    assert "shared_frame" not in sys.modules
    assert str(root) not in sys.path and str(script.parent) not in sys.path


def test_a_changed_helper_is_read_again_on_the_next_run(tmp_path):
    root, script = _tree(tmp_path, 1)
    run_script(script, object())
    (root / "shared_frame.py").write_text("VALUE = 2\n")
    assert run_script(script, object()).SEEN == 2


def test_without_a_placemat_toml_only_the_scripts_own_folder_is_added(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "far_helper.py").write_text("X = 1\n")
    script = tmp_path / "a" / "b" / "S_layout.py"
    script.write_text("try:\n    import far_helper\n    FOUND = True\nexcept ImportError:\n    FOUND = False\n")
    assert run_script(script, object()).FOUND is False


def test_a_helper_above_the_script_is_part_of_its_fingerprint(tmp_path):
    """So a changed helper is a different run, never a replay of the old."""
    from placemat.project import script_fingerprint
    root, script = _tree(tmp_path, 1)
    before = script_fingerprint(script)
    (root / "shared_frame.py").write_text("VALUE = 2\n")
    assert script_fingerprint(script) != before
