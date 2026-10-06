"""A scan of an item that owns a net tie, or meets another item's, is judged
natively (Occupancy.native_sweeper), KiCad's net-tie exclusion and all: it
accepts the candidates and chooses the spot the pure-Python sweep does."""
import dataclasses

import pytest

from placemat import placer
from placemat.occupancy import Occupancy
from placemat.placement import Placement
from placemat.settings import Settings
from placemat.values import Face, Location
from tests.conftest import needs_native
from tests.fixtures import board_geometry, footprint
from tests.test_pad_on_pad_edge import _tie

pytestmark = needs_native

NETS = ("A", "B")


def _occupancy(movers, placed, envelope="courtyard", dx=3.5, dy=1.4, cells=()):
    """The parts `movers` stand free; `placed` are committed where they are."""
    # a field of parts, so most spots near the hint are refused
    fps = [footprint("P%d" % i, 10 + dx * (i // 12), 10 + dy * (i % 12), w=3.0, h=1.0, nets=NETS) for i in range(96)]
    fps += list(movers) + list(placed)
    occ = Occupancy(board_geometry(fps, cells=cells, width=45, height=45), edge_margin=1.0,
                    settings=dataclasses.replace(Settings(), place_envelope=envelope))
    for fp in fps:
        if fp not in movers:
            occ.commit(fp, Placement(fp.location, fp.rotation, fp.face))
    return occ


def _scan(occ, item, native, monkeypatch, rotations=(0, 90), radius=6.0, step=0.5):
    """(chosen, tried, rejected total, the candidates scored legal, the calls legal_bucket took)."""
    monkeypatch.setattr(placer, "NATIVE_SWEEP", native)
    calls = []
    real = Occupancy.legal_bucket

    def counting(self, it, placement, *a, **kw):
        calls.append(placement)
        return real(self, it, placement, *a, **kw)
    monkeypatch.setattr(Occupancy, "legal_bucket", counting)
    legal = set()
    geom_hint = Placement(Location(22.0, 22.0), 0, Face.FRONT)

    def score(cand):
        legal.add((cand.location.x, cand.location.y, cand.rotation))
        return cand.location.x + 0.37 * cand.location.y
    res = placer.scan(occ, item, geom_hint, radius, step, rotations=rotations, score=score)
    unscored = placer.scan(occ, item, geom_hint, radius, step, rotations=rotations)
    return (res.chosen, unscored.chosen, res.tried, sum(res.rejected.values()), legal, len(calls))


@pytest.mark.parametrize("envelope", ["courtyard", "physical"])
def test_a_cell_that_owns_a_net_tie_is_accepted_and_chosen_as_the_python_sweep_does(monkeypatch, envelope):
    tie = dataclasses.replace(_tie("NT", NETS), cell="grp")
    part = footprint("R", 21, 20, w=3.0, h=1.0, nets=NETS, cell="grp")
    occ = _occupancy([tie, part], [], envelope, cells=("grp",))
    cell = occ.geometry.cell("grp")
    py = _scan(occ, cell, False, monkeypatch)
    nat = _scan(occ, cell, True, monkeypatch)
    assert py[4], "the cell has somewhere to go"
    assert nat[:5] == py[:5]
    assert nat[5] == 0                   # no candidate is judged in Python


@pytest.mark.parametrize("envelope", ["courtyard", "physical"])
def test_an_item_meeting_another_items_net_tie_is_accepted_and_chosen_as_the_python_sweep_does(monkeypatch, envelope):
    tie = dataclasses.replace(_tie("NT", NETS), ref="NT", location=Location(22.0, 22.0))
    mover = footprint("Q", 22, 22, w=2.0, h=1.0, nets=NETS)
    occ = _occupancy([mover], [tie], envelope, dx=6.0, dy=3.0)
    py = _scan(occ, mover, False, monkeypatch)
    nat = _scan(occ, mover, True, monkeypatch)
    assert py[4], "the part has somewhere to go"
    assert nat[:5] == py[:5]
    assert nat[5] == 0


def _searched_board(envelope):
    """Parts that search for a place beside a net tie they do not own, on nets the placed parts carry:
    the scorer weighs each legal candidate."""
    from placemat.layout import Board
    from placemat.values import Part
    tie = dataclasses.replace(_tie("NT", NETS), ref="NT", location=Location(30.0, 30.0))
    fixed = [footprint("P1", 24, 30, w=3.0, h=1.0, nets=NETS), footprint("P2", 36, 30, w=3.0, h=1.0, nets=NETS)]
    movers = [footprint("Q%d" % i, 10, 10 + 3 * i, w=3.0, h=1.0, nets=NETS) for i in range(3)]
    geom = board_geometry(fixed + movers + [tie], width=60, height=60, clearance=0.2)
    b = Board(geom, edge_margin=1.0, keep_going=True, settings=dataclasses.replace(Settings(), place_envelope=envelope))
    b.place(Part("p1"), at=Location(24, 30), rotation=0)
    b.place(Part("p2"), at=Location(36, 30), rotation=0)
    b.place(Part("nt"), at=Location(30, 30), rotation=0)
    for m in movers:
        b.place(Part(m.inst))
    return b


@pytest.mark.parametrize("envelope", ["courtyard", "physical"])
def test_a_search_beside_a_net_tie_places_as_the_python_path_does_and_scores_natively(monkeypatch, envelope):
    from placemat import occupancy
    scored = []
    real = occupancy.NativeSweeper._sweep

    def spy(self, index, triples, stop_at_first, scoring):
        scored.append(scoring is not None)
        return real(self, index, triples, stop_at_first, scoring)

    def run(native):
        monkeypatch.setattr(placer, "NATIVE_SWEEP", native)
        plan = _searched_board(envelope).resolve()
        return ([(s.item, s.placement and (s.placement.location.x, s.placement.location.y, s.placement.rotation))
                 for s in plan.steps], sorted(plan.findings))
    py = run(False)
    monkeypatch.setattr(occupancy.NativeSweeper, "_sweep", spy)
    nat = run(True)
    assert nat == py
    assert any(s[1] for s in py[0] if s[0].startswith("q")), "the searched parts are placed"
    assert any(scored), "a sweep past a net tie it does not own scores natively"
