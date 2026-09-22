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
