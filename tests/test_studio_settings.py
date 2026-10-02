"""[studio] settings: defaults, a placemat.toml, and no effect on a run's id."""
import json

import pytest

from placemat.reuse import placement_settings
from placemat.settings import Settings, SettingsError, load


def test_defaults():
    s = Settings()
    assert (s.studio_port, s.studio_debounce_ms, s.studio_open, s.studio_keep) == (0, 300, True, 10)
    assert s.studio_poll_ms > 0 and s.studio_cancel_grace_ms > 0


def test_a_placemat_toml_sets_them(tmp_path):
    (tmp_path / "placemat.toml").write_text("[studio]\nport = 8123\ndebounce_ms = 50\nopen = false\nkeep = 3\n")
    s = load(tmp_path)
    assert (s.studio_port, s.studio_debounce_ms, s.studio_open, s.studio_keep) == (8123, 50, False, 3)


@pytest.mark.parametrize("line", ["keep = 0", "poll_ms = 0", "port = -1", "debounce_ms = -5", "open = 1"])
def test_values_that_cannot_work_are_refused(tmp_path, line):
    (tmp_path / "placemat.toml").write_text("[studio]\n%s\n" % line)
    with pytest.raises(SettingsError):
        load(tmp_path)


def test_studio_settings_are_not_part_of_a_run_id_or_a_reuse_context():
    a, b = Settings(), Settings(studio_port=9000, studio_debounce_ms=1, studio_open=False, studio_keep=2)
    assert a.json() == b.json()
    assert placement_settings(a) == placement_settings(b)
    assert not any(k.startswith("studio_") for k in json.loads(a.json()))
