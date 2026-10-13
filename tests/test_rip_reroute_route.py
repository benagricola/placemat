"""Rip and reroute through a whole route: a stand-in router that lays copper (tests/rip_helpers.py), real pcbnew and
DRC."""
import json

import pytest

from placemat.kicad.route import route_board
from placemat.settings import Settings, bind
from tests.conftest import needs_kicad
from tests.phase_helpers import phases
from tests.rip_helpers import rip_board, toy_router


@pytest.fixture
def toy(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    krt = toy_router(tmp_path)
    monkeypatch.setenv("FAKE_ROUTER_LOG", str(tmp_path / "calls"))

    class Toy:
        def calls(self):
            log = tmp_path / "calls"
            return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

        def route(self, *raw, pcb=None, settings=None, **kw):
            with bind(Settings(**(settings or {}))):
                return route_board(pcb or rip_board(tmp_path), tmp_path / "route", router_dir_override=str(krt),
                                   layers=["F.Cu", "B.Cu"], phases=phases(*raw), **kw)
    return Toy()


A = {"name": "a", "nets": ["A"]}
B = {"name": "b", "nets": ["B"]}


@needs_kicad
def test_every_phase_records_its_rip_and_rip_off_changes_nothing(toy):
    report = toy.route(A, B, settings={"route_rip_attempts": 0})
    assert [p["rip"] for p in report.phases] == [{"attempts": [], "skipped": []}] * 2
    assert [p["joined"] for p in report.phases] == [1, 0]
