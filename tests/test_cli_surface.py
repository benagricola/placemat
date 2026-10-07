"""Every command and long option `placemat --help` exposes is listed in tests/surface/cli.txt: a removed one must be
gone from both, a new one added to the list on purpose (roadmap, "Keeping dead code out")."""
import argparse
from pathlib import Path

from placemat.cli import parser

LIST = Path(__file__).with_name("surface") / "cli.txt"


def surface() -> list:
    root = parser()
    sub = next(a for a in root._actions if isinstance(a, argparse._SubParsersAction))
    out = set()
    for name, sp in sub.choices.items():
        out.add(name)
        for action in sp._actions:
            out |= {"%s %s" % (name, o) for o in action.option_strings if o.startswith("--") and o != "--help"}
    return sorted(out)


def test_the_cli_surface_is_the_listed_one():
    listed = [l.strip() for l in LIST.read_text().splitlines() if l.strip() and not l.startswith("#")]
    got = surface()
    assert sorted(listed) == got, "added: %s; gone: %s" % (sorted(set(got) - set(listed)), sorted(set(listed) - set(got)))
