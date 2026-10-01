"""[facts] holds one confirmed digest per script, in the nearest existing
placemat.toml: `placemat facts --confirm` beside a module writes the
board's own toml, never a new one that would cut the module off from the
board's shared helpers."""
import tomllib

from tests.conftest import needs_kicad
from tests.test_facts_cli import _board_and_script


def test_write_confirmed_keys_a_digest_per_script_in_a_facts_boards_table(tmp_path):
    from placemat.facts import write_confirmed
    p = tmp_path / "placemat.toml"
    p.write_text("[place]\nstep = 0.1\n")
    write_confirmed(p, "aaa", key="Core_layout.py")
    write_confirmed(p, "bbb", key="modules/m/M_layout.py")
    write_confirmed(p, "ccc", key="modules/m/M_layout.py")
    data = tomllib.loads(p.read_text())
    assert data["facts"]["boards"] == {"Core_layout.py": "aaa", "modules/m/M_layout.py": "ccc"}
    assert data["place"]["step"] == 0.1


def test_write_confirmed_migrates_an_old_single_key_that_matches(tmp_path):
    from placemat.facts import write_confirmed
    p = tmp_path / "placemat.toml"
    p.write_text('[facts]\nconfirmed = "aaa"\n')
    write_confirmed(p, "aaa", key="Core_layout.py")
    data = tomllib.loads(p.read_text())
    assert "confirmed" not in data["facts"]
    assert data["facts"]["boards"] == {"Core_layout.py": "aaa"}


def test_write_confirmed_keeps_an_old_single_key_another_script_may_hold(tmp_path):
    from placemat.facts import write_confirmed
    p = tmp_path / "placemat.toml"
    p.write_text('[facts]\nconfirmed = "aaa"\n')
    write_confirmed(p, "bbb", key="modules/m/M_layout.py")
    data = tomllib.loads(p.read_text())
    assert data["facts"]["confirmed"] == "aaa"
    assert data["facts"]["boards"] == {"modules/m/M_layout.py": "bbb"}


def test_confirmed_digest_reads_the_script_entry_then_the_old_single_key(tmp_path):
    from placemat import settings as S
    from placemat.facts import confirmed_digest
    (tmp_path / "modules" / "m").mkdir(parents=True)
    (tmp_path / "placemat.toml").write_text(
        '[facts]\nconfirmed = "old"\n[facts.boards]\n"modules/m/M_layout.py" = "mod"\n')
    cfg = S.load(tmp_path / "modules" / "m")
    assert confirmed_digest(cfg, tmp_path / "modules" / "m" / "M_layout.py") == "mod"
    assert confirmed_digest(cfg, tmp_path / "Core_layout.py") == "old"
    assert confirmed_digest(S.Settings(), tmp_path / "Core_layout.py") == ""


def test_facts_boards_does_not_feed_the_run_id(tmp_path):
    import json
    from placemat import settings as S
    (tmp_path / "placemat.toml").write_text('[facts.boards]\n"a.py" = "x"\n')
    got = S.load(tmp_path)
    assert got.facts_boards == {"a.py": "x"}
    assert "facts_boards" not in json.loads(got.json())
    assert got.json() == S.Settings().json()


def _project_with_a_module(tmp_path, board):
    """core/placemat.toml, a helper in core, and a module under
    core/modules/m with its own .zen and layout."""
    core = tmp_path / "core"
    mod = core / "modules" / "m"
    mod.mkdir(parents=True)
    for d, name in ((core, "Core"), (mod, "M")):
        (d / ("%s.zen" % name.lower())).write_text(
            'Board(\n    name = "%s",\n    layout_path = "layout",\n)\n' % name)
        (d / "layout").mkdir()
        board.Save(str(d / "layout" / "layout.kicad_pcb"))
        (d / ("%s_layout.py" % name)).write_text("import shared_helper\n" if d == mod else "")
    (core / "shared_helper.py").write_text("VALUE = 1\n")
    (core / "fab-profile.json").write_text(
        '{"via": {"micro": "no", "blind": "no", "buried": "no"}, "min": {"track_mm": 0.09}}')
    (core / "placemat.toml").write_text("[place]\nstep = 0.5\n")
    return core, core / "Core_layout.py", mod / "M_layout.py"


@needs_kicad
def test_facts_confirm_beside_a_module_writes_the_nearest_existing_toml(tmp_path):
    import pcbnew
    from placemat import cli
    from placemat.context import _import_dirs
    core, core_script, mod_script = _project_with_a_module(tmp_path, pcbnew.CreateEmptyBoard())
    assert cli.main(["facts", str(mod_script), "--confirm"]) == 0
    assert not (mod_script.parent / "placemat.toml").exists()
    assert core in _import_dirs(mod_script)
    data = tomllib.loads((core / "placemat.toml").read_text())
    assert list(data["facts"]["boards"]) == ["modules/m/M_layout.py"]
    assert data["place"]["step"] == 0.5


@needs_kicad
def test_facts_confirmations_of_a_board_and_its_module_are_independent(tmp_path):
    import pcbnew
    from placemat import cli
    core, core_script, mod_script = _project_with_a_module(tmp_path, pcbnew.CreateEmptyBoard())
    mod_pcb = mod_script.parent / "layout" / "layout.kicad_pcb"
    mod_board = pcbnew.CreateEmptyBoard()
    mod_board.SetCopperLayerCount(4)                 # the module's facts differ from the board's
    mod_board.Save(str(mod_pcb))
    assert cli.main(["facts", str(core_script), "--confirm"]) == 0
    assert cli.main(["facts", str(mod_script), "--confirm"]) == 0
    data = tomllib.loads((core / "placemat.toml").read_text())
    assert set(data["facts"]["boards"]) == {"Core_layout.py", "modules/m/M_layout.py"}
    assert len(set(data["facts"]["boards"].values())) == 2
    assert cli.main(["facts", str(core_script)]) == 0
    assert cli.main(["facts", str(mod_script)]) == 0
    mod_board.SetCopperLayerCount(2)                 # the module changes: only it is unconfirmed
    mod_board.Save(str(mod_pcb))
    assert cli.main(["facts", str(core_script)]) == 0
    assert cli.main(["facts", str(mod_script)]) == 1


@needs_kicad
def test_facts_reads_the_old_single_key_and_migrates_on_confirm(tmp_path):
    from placemat import cli
    script = _board_and_script(tmp_path, fab_profile=True)
    assert cli.main(["facts", str(script), "--confirm"]) == 0
    toml = tmp_path / "placemat.toml"
    digest = tomllib.loads(toml.read_text())["facts"]["boards"]["Widget_layout.py"]
    toml.write_text('[facts]\nconfirmed = "%s"\n' % digest)
    assert cli.main(["facts", str(script)]) == 0
    assert cli.main(["facts", str(script), "--confirm"]) == 0
    data = tomllib.loads(toml.read_text())
    assert "confirmed" not in data["facts"] and data["facts"]["boards"] == {"Widget_layout.py": digest}
