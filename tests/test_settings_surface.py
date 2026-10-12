"""Every `[section] key` the settings accept is listed in tests/surface/settings.txt, and the api.md table is generated
from the same fields (test_settings_docs)."""
from pathlib import Path

from placemat.settings import Settings, split_key

LIST = Path(__file__).with_name("surface") / "settings.txt"


def test_the_settings_surface_is_the_listed_one():
    listed = [l.strip() for l in LIST.read_text().splitlines() if l.strip() and not l.startswith("#")]
    got = sorted("%s.%s" % split_key(k) for k in Settings.keys())
    assert sorted(listed) == got, "added: %s; gone: %s" % (sorted(set(got) - set(listed)), sorted(set(listed) - set(got)))
