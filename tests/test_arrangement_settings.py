import pytest

from placemat import settings as S
from placemat.settings import Settings, SettingsError


def test_the_arrangement_settings_have_the_documented_defaults():
    s = Settings()
    assert s.place_arrangements is True
    assert s.place_arrangement_options_max == 4
    assert s.place_arrangements_max == 8
    assert s.place_arrangement_note_chars == 4000
    assert s.place_extent_notice_mm == 1.0
    assert s.score_arrangement == 0.0


def test_they_are_set_from_placemat_toml(tmp_path):
    (tmp_path / "placemat.toml").write_text(
        "[place]\narrangements = false\narrangement_options_max = 2\narrangements_max = 5\n"
        "arrangement_note_chars = 100\nextent_notice_mm = 0.5\n[score]\narrangement = 1.5\n")
    s = S.load(tmp_path)
    assert (s.place_arrangements, s.place_arrangement_options_max, s.place_arrangements_max) == (False, 2, 5)
    assert (s.place_arrangement_note_chars, s.place_extent_notice_mm, s.score_arrangement) == (100, 0.5, 1.5)


@pytest.mark.parametrize("text", [
    "[score]\narrangement = -0.1\n", "[place]\narrangements_max = 0\n", "[place]\narrangement_options_max = 0\n",
    "[place]\narrangement_note_chars = 0\n", "[place]\nextent_notice_mm = -1\n"])
def test_a_setting_that_cannot_work_is_refused(tmp_path, text):
    (tmp_path / "placemat.toml").write_text(text)
    with pytest.raises(SettingsError):
        S.load(tmp_path)
