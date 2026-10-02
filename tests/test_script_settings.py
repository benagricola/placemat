"""A placemat.toml shared by a parent and its module scripts sets one setting
differently for one script: `[scripts."<path>".<section>]`, keyed by the
script's path relative to the file, validated like the base sections."""
import json
import sys

import pytest

from placemat import settings as S
from placemat.context import run_script
from placemat.report import run_id

TOML = '''[solve]
enabled = false

[place]
step = 0.1

[scripts."modules/m/M_layout.py".solve]
enabled = true
iterations = 7
'''


def _tree(tmp_path, toml=TOML):
    root = tmp_path / "proj"
    (root / "modules" / "m").mkdir(parents=True)
    (root / "modules" / "n").mkdir(parents=True)
    (root / "placemat.toml").write_text(toml)
    for rel in ("Main_layout.py", "modules/m/M_layout.py", "modules/n/N_layout.py"):
        (root / rel).write_text("")
    return root


def test_each_script_sees_its_own_setting(tmp_path):
    root = _tree(tmp_path)
    parent = S.load(root, script=root / "Main_layout.py")
    module = S.load(root / "modules" / "m", script=root / "modules" / "m" / "M_layout.py")
    other = S.load(root / "modules" / "n", script=root / "modules" / "n" / "N_layout.py")
    assert (parent.solve_enabled, module.solve_enabled, other.solve_enabled) == (False, True, False)
    assert module.solve_iterations == 7 and parent.solve_iterations == S.Settings().solve_iterations
    assert module.place_step == 0.1                       # the base still applies


def test_without_a_script_the_base_applies(tmp_path):
    root = _tree(tmp_path)
    assert S.load(root / "modules" / "m").solve_enabled is False


def test_the_source_names_the_override(tmp_path):
    root = _tree(tmp_path)
    s = S.load(root, script=root / "modules" / "m" / "M_layout.py")
    assert s.source_of("solve_enabled") == '%s [scripts."modules/m/M_layout.py"]' % (root / "placemat.toml")
    assert s.source_of("place_step") == str(root / "placemat.toml")


def test_a_flag_beats_the_override(tmp_path):
    root = _tree(tmp_path)
    s = S.load(root, overrides={"solve_enabled": False}, script=root / "modules" / "m" / "M_layout.py")
    assert s.solve_enabled is False and s.source_of("solve_enabled") == "flag"


def test_run_ids_differ_when_only_the_override_differs(tmp_path):
    root = _tree(tmp_path)
    a = S.load(root, script=root / "Main_layout.py")
    b = S.load(root, script=root / "modules" / "m" / "M_layout.py")
    ids = [run_id("same script", b"same board", "1.0", s.json()) for s in (a, b)]
    assert ids[0] != ids[1]


@pytest.mark.parametrize("body, text", [
    ('[scripts."Main_layout.py".solve]\nenabeld = true\n', "solve.enabeld is not a setting"),
    ('[scripts."Main_layout.py".bogus]\nx = 1\n', "[bogus] is not a section"),
    ('[scripts."Main_layout.py".solve]\niterations = "many"\n', "solve.iterations must be"),
    ('[scripts."Gone_layout.py".solve]\nenabled = true\n', "no script Gone_layout.py"),
    ('[scripts."Main_layout.py".facts]\nconfirmed = "x"\n', "not set per script"),
    ('[scripts]\nbare = 1\n', "must be a table of sections"),
])
def test_a_bad_override_is_refused_for_every_script(tmp_path, body, text):
    root = _tree(tmp_path, body)
    with pytest.raises(S.SettingsError) as e:
        S.load(root)                                       # even with no script named
    assert text in str(e.value) and "placemat.toml" in str(e.value)


def test_an_override_in_an_outer_file_is_keyed_from_that_file(tmp_path):
    root = _tree(tmp_path, '[scripts."modules/m/M_layout.py".solve]\nenabled = true\n')
    (root / "modules" / "m" / "placemat.toml").write_text("[place]\nstep = 0.3\n")
    s = S.load(root / "modules" / "m", script=root / "modules" / "m" / "M_layout.py")
    assert s.solve_enabled is True and s.place_step == 0.3


def test_settings_command_shows_the_override_source(tmp_path, capsys):
    from placemat import cli
    root = _tree(tmp_path)
    (root / "modules" / "m" / "M.zen").write_text('Board(name = "m", layout = True)\n')
    script = root / "modules" / "m" / "M_layout.py"
    assert cli.main(["settings", str(script), "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out[out.index("{"):])
    assert data["solve_enabled"]["value"] is True
    assert "[scripts." in data["solve_enabled"]["source"]


def test_a_placemat_toml_beside_a_module_keeps_the_parent_s_helpers_importable(tmp_path):
    root = _tree(tmp_path, "")
    (root / "shared_frame.py").write_text("VALUE = 3\n")
    (root / "modules" / "m" / "placemat.toml").write_text("")
    script = root / "modules" / "m" / "M_layout.py"
    script.write_text("from shared_frame import VALUE\nSEEN = VALUE\n")
    assert run_script(script, object()).SEEN == 3
    assert "shared_frame" not in sys.modules
    assert str(root) not in sys.path


def test_the_fingerprint_follows_the_helper_past_a_nearer_placemat_toml(tmp_path):
    from placemat.project import script_fingerprint
    root = _tree(tmp_path, "")
    (root / "shared_frame.py").write_text("VALUE = 3\n")
    (root / "modules" / "m" / "placemat.toml").write_text("")
    script = root / "modules" / "m" / "M_layout.py"
    script.write_text("from shared_frame import VALUE\n")
    before = script_fingerprint(script)
    (root / "shared_frame.py").write_text("VALUE = 4\n")
    assert script_fingerprint(script) != before
