"""The pin map study's settings: each with its default, a list of turns refused when an entry is not a number, and none
of them able to stop a placement replaying."""
import pytest

from placemat.reuse import placement_settings
from placemat.settings import Settings, SettingsError, load


def test_every_pins_setting_has_its_default():
    s = Settings()
    assert (s.pins_exit_mm, s.pins_follow_series, s.pins_pair_weight, s.pins_impedance_weight, s.pins_length_weight,
            s.pins_bend_weight) == (0.5, True, 5.0, 3.0, 0.25, 0.005)
    assert (s.pins_rotations, s.pins_seeds, s.pins_anneal_moves, s.pins_anneal_start, s.pins_anneal_end) == \
        ((0.0, 90.0, 180.0, 270.0), 1, 100, 1.0, 0.02)
    assert (s.pins_budget_ms, s.pins_joint_combinations, s.pins_faces, s.pins_gain_min, s.pins_explore_top,
            s.pins_probe_budget_ms) == (100, 64, False, 0.05, 3, 5000)
    assert s.pins_placed_share_min == 0.8 and s.pins_group_weight == 4.0


def test_the_turns_are_read_from_the_toml_and_an_entry_that_is_not_a_number_is_refused(tmp_path):
    (tmp_path / "placemat.toml").write_text("[pins]\nrotations = [0, 45, 90]\nbudget_ms = 250\n")
    s = load(tmp_path)
    assert s.pins_rotations == (0, 45, 90) and s.pins_budget_ms == 250
    (tmp_path / "placemat.toml").write_text('[pins]\nrotations = [0, "ninety"]\n')
    with pytest.raises(SettingsError, match="pins.rotations"):
        load(tmp_path)
    (tmp_path / "placemat.toml").write_text("[pins]\nbudget_ms = 0\n")
    with pytest.raises(SettingsError, match="pins.budget_ms"):
        load(tmp_path)


def test_a_pins_setting_changes_no_placement_so_a_replay_still_holds():
    assert "pins_budget_ms" not in placement_settings(Settings())


@pytest.mark.parametrize("line", ["rotations = []", "rotations = [0, nan]", "rotations = [inf]",
                                  "anneal_start = 0.1\nanneal_end = 0.5"])
def test_a_list_of_turns_that_is_empty_or_not_finite_and_an_end_above_the_start_are_refused(tmp_path, line):
    (tmp_path / "placemat.toml").write_text("[pins]\n%s\n" % line)
    with pytest.raises(SettingsError, match="pins\\."):
        load(tmp_path)


def test_the_prefixes_of_the_series_parts_followed_are_a_setting(tmp_path):
    assert Settings().pins_follow_prefixes == ("R", "L", "FB")
    (tmp_path / "placemat.toml").write_text('[pins]\nfollow_prefixes = ["R"]\n')
    assert load(tmp_path).pins_follow_prefixes == ("R",)


def test_the_prefixes_setting_says_the_leading_letters_must_equal_a_prefix_in_any_case():
    from placemat.settings import describe
    text = describe("pins_follow_prefixes")
    assert "leading letters" in text and "any case" in text and "starts with" not in text
