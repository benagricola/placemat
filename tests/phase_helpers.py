"""Phases for tests that route: the rest phase alone, which routes what the old main pass did; and the capability
listing a stand-in router gives so a route takes it for the placemat fork."""
import json

from placemat.route_phase import parse_phases

SIGNALS = ({"name": "signals"},)
CAPABILITIES = {"modules": {"route.py": True}, "flags": {"route.py": ["--connections", "--bus-nets"]}}


def phases(*raw):
    return parse_phases(raw or SIGNALS)


def fake_capabilities(krt) -> None:
    """A stand-in router checkout's krt_capabilities.py: it lists every flag a phase route needs (route.REQUIRES)."""
    (krt / "krt_capabilities.py").write_text("print(%r)\n" % json.dumps(CAPABILITIES))
