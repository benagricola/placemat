"""A scan of an item that owns a net tie, or meets another item's, is still
judged natively (Occupancy.native_sweeper): the native pass leaves the tie
shapes out and refuses what it refuses without them, and the candidates it
accepts are judged in full in Python, where KiCad's net-tie exclusion is. It
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
    assert nat[5] < py[5] / 2            # legal_bucket judges the native survivors, not every candidate


@pytest.mark.parametrize("envelope", ["courtyard", "physical"])
def test_an_item_meeting_another_items_net_tie_is_accepted_and_chosen_as_the_python_sweep_does(monkeypatch, envelope):
    tie = dataclasses.replace(_tie("NT", NETS), ref="NT", location=Location(22.0, 22.0))
    mover = footprint("Q", 22, 22, w=2.0, h=1.0, nets=NETS)
    occ = _occupancy([mover], [tie], envelope, dx=6.0, dy=3.0)
    py = _scan(occ, mover, False, monkeypatch)
    nat = _scan(occ, mover, True, monkeypatch)
    assert py[4], "the part has somewhere to go"
    assert nat[:5] == py[:5]
    assert nat[5] < py[5] / 2
