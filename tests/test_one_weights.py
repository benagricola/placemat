"""Pin candidates read the shared crossing and airwire price definitions."""
from dataclasses import replace

import pytest

from placemat.pinmap import digest
from placemat.pinmap_core import params_of, study_group, native_core
from placemat.settings import Settings
from tests.pinmap_boards import input_of, reversed_four, settings


@pytest.mark.parametrize('crossing', [0.0, 4.0, 10.0])
def test_pin_generator_uses_common_crossing_units(crossing):
    cfg = replace(Settings(), score_crossing=crossing, score_crossing_pair_net=17.0,
                  score_impedance=7.0, score_crossing_plane=0.8)
    assert params_of(cfg, ('U1',))['weights'] == (
        17.0, 7.0, 0.8, 1.0 / crossing if crossing else 0.0,
        cfg.pins_bend_weight, cfg.pins_group_weight)


@pytest.mark.parametrize('native', [False, True])
def test_shared_pair_price_changes_actual_pin_study_crossing_counts(native):
    if native and native_core() is None:
        pytest.skip('native pin core unavailable')
    inp, _ = input_of(*reversed_four(), partners={'A': 'OTHER'})
    for price in (2.0, 50.0):
        cfg = settings(score_crossing_pair_net=price, pins_rotations=(0.0,))
        group = study_group(inp, ('U1',), cfg, native=native)
        assert group.present.weighted == 3.0 + 3.0 * price
        assert group.results[0].breakdown.weighted == 0.0


@pytest.mark.parametrize('key', ['score_crossing', 'score_crossing_pair_net',
                                 'score_impedance', 'score_crossing_plane'])
def test_pin_generator_cache_changes_with_each_shared_weight(key):
    inp, problems = input_of(*reversed_four())
    cfg = Settings()
    changed = replace(cfg, **{key: getattr(cfg, key) + 1})
    assert digest(inp, problems, frozenset(), cfg) != digest(inp, problems, frozenset(), changed)
