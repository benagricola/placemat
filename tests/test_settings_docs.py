"""Settings documented as data: every setting's unit and meaning live in settings.py, the api.md table is generated
from them, `placemat settings --example` writes a complete commented placemat.toml that loads to the defaults, and a setting's old name from before a rename is refused as unknown."""
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
@pytest.mark.parametrize("old, section, key", [("rank_area", "rank", "area"), ("copper_arc_radius_widths", "copper", "arc_radius_widths"),
                                               ("place_via_share", "place", "via_share"), ("score_priority_low", "score", "priority_low")])
def test_a_name_from_before_the_renames_is_an_unknown_setting(old, section, key, tmp_path):
    assert old not in Settings.keys()
    (tmp_path / "placemat.toml").write_text("[%s]\n%s = 1\n" % (section, key))
    with pytest.raises(SettingsError, match="%s.%s is not a setting placemat has" % (section, key)):
        load(tmp_path)


def test_every_name_in_a_validation_set_is_a_real_setting():
    """A missing comma between two names makes one that is no setting (and drops the check on both)."""
    known = set(Settings.keys())
    for label, names in (("_ABOVE_ZERO", S._ABOVE_ZERO), ("_AT_LEAST_ZERO", S._AT_LEAST_ZERO), ("_AT_LEAST_TWO", S._AT_LEAST_TWO),
                         ("_UNIT_INTERVAL", S._UNIT_INTERVAL), ("_CHOICES", S._CHOICES)):
        assert set(names) <= known, "%s names no setting: %s" % (label, sorted(set(names) - known))
    assert "studio_port" in S._AT_LEAST_ZERO and "best_crossing_noise" in S._AT_LEAST_ZERO
