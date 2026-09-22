"""placemat.toml: one home for every behavioural constant, and the rules
for where a value came from."""
import json

import pytest

from placemat import settings as S


def test_defaults_are_todays_values():
    s = S.Settings()
    assert s.rank_area == 0.7 and s.rank_pins == 0.3
    assert s.place_step == 0.2 and s.place_radius == 3.0
    assert s.place_coarse_steps == 4 and s.place_coarse_from == 12.0
    assert s.place_refine_around == 3
    assert s.place_block_gap_step == 0.05 and s.place_block_gap_reach == 2.0
    assert s.place_courtyard_touch == 0.02 and s.place_conflict_gap == 1.0
    assert s.copper_chamfer == 1.0 and s.copper_bridge_half == 1.1
    assert s.copper_plane_inset == 0.4 and s.copper_pour_stroke == 0.2
    assert s.label_size == 1.0 and s.label_thickness == 0.15
    assert s.geometry_arc_sag == 0.02 and s.geometry_index_cells == 16
    assert s.geometry_arc_error_nm == 5000
    assert s.check_ambient_c == 100.0 and s.check_keep_out_mm == 2.0
    assert s.drc_refill_zones is True
    assert s.timeout_generate == 900 and s.timeout_drc == 600


def test_every_attribute_maps_to_a_section_and_key():
    """The TOML shape is derived, never hand-mapped: [place] step is place_step."""
    for name in S.Settings.keys():
        assert "_" in name, name
        section, key = S.split_key(name)
        assert S.join_key(section, key) == name


def test_nothing_bound_gives_the_defaults():
    assert S.active() == S.Settings()


def test_bind_scopes_a_settings_and_restores_it():
    mine = S.Settings(place_step=0.05)
    with S.bind(mine):
        assert S.active().place_step == 0.05
    assert S.active().place_step == 0.2


def test_json_is_canonical_and_ignores_sources():
    a = S.Settings(place_step=0.1)
    b = S.Settings(place_step=0.1, sources={"place_step": "somewhere.toml"})
    assert a.json() == b.json()
    assert json.loads(a.json())["place_step"] == 0.1


def test_json_differs_when_a_value_differs():
    assert S.Settings(place_step=0.1).json() != S.Settings(place_step=0.2).json()


def test_source_of_defaults_to_the_word_default():
    assert S.Settings().source_of("place_step") == "default"


def _toml(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_no_file_anywhere_gives_the_defaults(tmp_path):
    board = tmp_path / "boards" / "main"
    board.mkdir(parents=True)
    s = S.load(board)
    assert s == S.Settings()
    assert all(s.source_of(k) == "default" for k in S.Settings.keys())


def test_a_file_two_levels_up_is_found(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstep = 0.05\n")
    board = tmp_path / "boards" / "main"
    board.mkdir(parents=True)
    s = S.load(board)
    assert s.place_step == 0.05
    assert s.source_of("place_step") == str(tmp_path / "placemat.toml")
    assert s.place_radius == 3.0 and s.source_of("place_radius") == "default"


def test_the_nearest_file_wins_per_key_and_the_outer_one_still_contributes(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstep = 0.05\nradius = 9.0\n")
    board = tmp_path / "boards" / "main"
    _toml(board / "placemat.toml", "[place]\nstep = 0.01\n")
    s = S.load(board)
    assert s.place_step == 0.01                       # the nearest file
    assert s.place_radius == 9.0                      # only the outer file has it
    assert s.source_of("place_step") == str(board / "placemat.toml")
    assert s.source_of("place_radius") == str(tmp_path / "placemat.toml")


def test_a_sub_table_loads(tmp_path):
    _toml(tmp_path / "placemat.toml", '[check.limits]\n"hot-loop" = 20.0\n')
    s = S.load(tmp_path)
    assert s.check_limits == {"hot-loop": 20.0}


def test_a_list_valued_key_loads_as_a_tuple(tmp_path):
    _toml(tmp_path / "placemat.toml", '[drc]\nreal_kinds = ["clearance"]\n')
    s = S.load(tmp_path)
    assert s.drc_real_kinds == ("clearance",)


def test_a_file_is_read_once_even_when_the_start_is_the_file_s_own_directory(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstep = 0.05\n")
    assert S.load(tmp_path).place_step == 0.05


def test_an_unknown_section_is_an_error_naming_the_file(tmp_path):
    _toml(tmp_path / "placemat.toml", "[plaec]\nstep = 0.05\n")
    with pytest.raises(S.SettingsError) as e:
        S.load(tmp_path)
    assert "placemat.toml" in str(e.value) and "plaec" in str(e.value)


def test_an_unknown_key_is_an_error_suggesting_the_nearest(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstepp = 0.05\n")
    with pytest.raises(S.SettingsError) as e:
        S.load(tmp_path)
    assert "place.stepp" in str(e.value) and "place.step" in str(e.value)


def test_a_wrong_type_is_an_error(tmp_path):
    _toml(tmp_path / "placemat.toml", '[place]\nstep = "small"\n')
    with pytest.raises(S.SettingsError) as e:
        S.load(tmp_path)
    assert "place.step" in str(e.value) and "number" in str(e.value)


def test_a_value_under_its_floor_is_an_error(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstep = 0.0\n")
    with pytest.raises(S.SettingsError) as e:
        S.load(tmp_path)
    assert "place.step" in str(e.value) and "greater than 0" in str(e.value)


def test_a_negative_weight_is_an_error(tmp_path):
    _toml(tmp_path / "placemat.toml", "[rank]\narea = -1.0\n")
    with pytest.raises(S.SettingsError):
        S.load(tmp_path)


def test_a_zero_weight_is_allowed(tmp_path):
    """Weighting pins at nothing is a legitimate choice; weighting a step at
    nothing is a scan that never moves."""
    _toml(tmp_path / "placemat.toml", "[rank]\npins = 0.0\n")
    assert S.load(tmp_path).rank_pins == 0.0


def test_an_error_in_an_outer_file_still_names_that_file(tmp_path):
    _toml(tmp_path / "placemat.toml", "[place]\nstepp = 1\n")
    board = tmp_path / "boards" / "main"
    _toml(board / "placemat.toml", "[place]\nstep = 0.01\n")
    with pytest.raises(S.SettingsError) as e:
        S.load(board)
    assert str(tmp_path / "placemat.toml") in str(e.value)


def test_a_flag_beats_the_file_and_the_source_says_so(tmp_path):
    _toml(tmp_path / "placemat.toml", "[check]\nambient_c = 85.0\n")
    s = S.load(tmp_path, overrides={"check_ambient_c": 60.0})
    assert s.check_ambient_c == 60.0 and s.source_of("check_ambient_c") == "flag"


def test_a_flag_left_off_falls_to_the_file(tmp_path):
    _toml(tmp_path / "placemat.toml", "[check]\nambient_c = 85.0\n")
    s = S.load(tmp_path, overrides={})
    assert s.check_ambient_c == 85.0


def test_overrides_from_args_only_carries_what_was_given():
    import argparse
    from placemat import cli
    args = argparse.Namespace(ambient=None, keep_out=2.5, rise=None, copper_oz=None, limit=[])
    assert cli.overrides_from(args) == {"check_keep_out_mm": 2.5}


def test_overrides_from_args_reads_limit_pairs():
    import argparse
    from placemat import cli
    args = argparse.Namespace(ambient=None, keep_out=None, rise=None, copper_oz=None,
                              limit=["hot-loop=20"])
    assert cli.overrides_from(args) == {"check_limits": {"hot-loop": 20.0}}


def test_the_settings_command_prints_every_key_and_its_source(tmp_path, capsys):
    import argparse
    from placemat import cli
    _toml(tmp_path / "placemat.toml", "[place]\nstep = 0.05\n")
    args = argparse.Namespace(where=str(tmp_path), json=False)
    assert cli.cmd_settings(args) == 0
    out = capsys.readouterr().out
    assert "place.step" in out and "0.05" in out and "placemat.toml" in out
    assert "rank.area" in out and "default" in out
