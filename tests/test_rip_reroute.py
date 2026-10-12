"""Rip and reroute (kicad/rip_reroute.py): the pure parts."""
from placemat.settings import Settings


def test_rip_and_reroute_is_on_by_default_with_its_limits():
    s = Settings()
    assert (s.route_rip_attempts, s.route_rip_max_nets) == (4, 3)


def test_a_negative_rip_limit_is_refused_at_load(tmp_path):
    import pytest
    from placemat.settings import SettingsError, load
    for key in ("rip_attempts", "rip_max_nets"):
        (tmp_path / "placemat.toml").write_text("[route]\n%s = -1\n" % key)
        with pytest.raises(SettingsError):
            load(tmp_path)
    (tmp_path / "placemat.toml").write_text("[route]\nrip_attempts = 0\nrip_max_nets = 0\n")
    assert (load(tmp_path).route_rip_attempts, load(tmp_path).route_rip_max_nets) == (0, 0)
