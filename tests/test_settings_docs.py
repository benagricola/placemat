"""Settings documented as data: every setting's unit and meaning live in settings.py, the api.md table is generated
from them, `placemat settings --example` writes a complete commented placemat.toml that loads to the defaults, and a
renamed setting's old name still loads, with a setup notice naming the new one."""
import dataclasses
import re
import tomllib
from pathlib import Path

import pytest

from placemat import settings as S
from placemat.settings import Settings, SettingsError, load

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "skills/placemat/references/api.md"


def test_every_setting_has_a_unit_and_a_description_as_data():
    for name in Settings.keys():
        meta = S.meta(name)
        assert meta["doc"].strip() and meta["unit"] in S.UNITS, name
    assert set(S.SECTIONS) == {S.split_key(k)[0] for k in Settings.keys()}
    assert all(S.SECTIONS[s].strip() for s in S.SECTIONS)


def test_a_setting_with_choices_says_which_in_its_docs():
    for name, choices in S._CHOICES.items():
        assert S.meta(name)["unit"] == "choice"
        assert all(c in S.describe(name) for c in choices), name


def test_the_api_table_is_the_generated_one():
    text = API.read_text()
    m = re.search(r"<!-- settings-table:begin -->\n(.*?)\n<!-- settings-table:end -->", text, re.S)
    assert m, "api.md needs the settings-table markers"
    assert m.group(1) == S.docs_table(), "api.md's settings table is out of date: run `placemat settings --markdown` and paste it between the markers"


def test_the_example_toml_is_valid_complete_and_loads_to_the_defaults(tmp_path):
    text = S.example_toml()
    data = tomllib.loads(text)
    (tmp_path / "placemat.toml").write_text(text)
    assert load(tmp_path) == Settings()                          # compares values; sources are not part of equality
    # every section and every setting is there (a None default as a comment: TOML has no null)
    for name in Settings.keys():
        section, key = S.split_key(name)
        dotted = "%s.%s" % (section, key)
        if name in S._SUBTABLES_BY_NAME:
            assert dotted in text, name
            continue
        assert re.search(r"^(# )?%s = " % re.escape(key), text, re.M), name
    for section in S.SECTIONS:
        assert "[%s]" % section in text
    assert set(data) <= set(S.SECTIONS)


def test_every_example_entry_is_commented_with_its_meaning_unit_and_default():
    text = S.example_toml()
    block = text.split("[place]")[1].split("\n[")[0]
    lines = block.splitlines()
    i = next(k for k, l in enumerate(lines) if l.startswith("step = "))
    above = "\n".join(lines[max(0, i - 6):i])
    assert "mm" in above and "default 0.2" in above and "step" in above.lower()
    assert S.SECTIONS["place"] in text


def test_the_cli_writes_the_example_to_a_file_or_stdout(tmp_path, capsys):
    from placemat import cli
    out = tmp_path / "placemat.toml"
    assert cli.main(["settings", "--example", "--output", str(out)]) == 0
    assert out.read_text() == S.example_toml()
    assert cli.main(["settings", "--example"]) == 0
    assert capsys.readouterr().out.strip() == S.example_toml().strip()


# ---------------------------------------------------------------- renames
def test_the_renames_are_data_and_each_new_name_is_a_setting_the_old_is_not():
    assert len(S.RENAMED) >= 25
    for old, new in S.RENAMED.items():
        assert new in Settings.keys() and old not in Settings.keys(), (old, new)
    assert S.RENAMED["copper_arc_radius_widths"] == "copper_arc_radius_track_widths"


def _other_than_default(name):
    default = getattr(Settings(), name)
    if default is None:
        return 7
    if isinstance(default, bool):
        return not default
    if isinstance(default, (int, float)):
        return default + 1
    return default


@pytest.mark.parametrize("old", sorted(S.RENAMED))
def test_an_old_name_still_loads_into_the_new_one_with_a_notice(old, tmp_path):
    new = S.RENAMED[old]
    value = _other_than_default(new)
    section, key = S.split_key(old)
    (tmp_path / "placemat.toml").write_text("[%s]\n%s = %s\n" % (section, key, S._toml_value(value)))
    s = load(tmp_path)
    assert getattr(s, new) == value
    notice = next(n for n in s.notices if "%s.%s" % (section, key) in n)
    assert "%s.%s" % S.split_key(new) in notice and "one release" in notice


def test_an_old_and_a_new_name_together_are_refused(tmp_path):
    (tmp_path / "placemat.toml").write_text("[copper]\narc_radius_widths = 4.0\narc_radius_track_widths = 5.0\n")
    with pytest.raises(SettingsError, match="arc_radius_track_widths.*arc_radius_widths|both"):
        load(tmp_path)


def test_an_old_name_works_in_a_per_script_table_too(tmp_path):
    (tmp_path / "M_layout.py").write_text("")
    (tmp_path / "placemat.toml").write_text('[scripts."M_layout.py".copper]\narc_radius_widths = 4.0\n')
    s = load(tmp_path, script=tmp_path / "M_layout.py")
    assert s.copper_arc_radius_track_widths == 4.0 and any("copper.arc_radius_widths" in n for n in s.notices)


def test_the_notice_reaches_the_plan_as_a_setup_notice(tmp_path):
    from placemat.layout import Board
    from tests.fixtures import board_geometry, footprint
    (tmp_path / "placemat.toml").write_text("[copper]\narc_radius_widths = 4.0\n")
    cfg = load(tmp_path)
    b = Board(board_geometry([footprint("R1", 5, 5, inst="r1")], width=20, height=20), settings=cfg)
    from placemat.values import Location, Part
    b.place(Part("r1"), at=Location(10, 10))
    plan = b.resolve()
    found = [f for f in plan.findings if f.kind == "setup" and "copper.arc_radius_track_widths" in str(f)]
    assert found and found[0].severity == "notice"


def test_the_new_names_are_what_the_docs_say():
    text = API.read_text()
    for old in S.RENAMED:
        dotted = old.replace("_", ".", 1)
        assert "`%s`" % dotted not in text, "%s is still in api.md" % dotted
