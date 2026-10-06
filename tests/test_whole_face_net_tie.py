"""A first-legal scan over a whole face (`Layout._scan_whole_face`) of an item that meets net ties: the native pass
judges KiCad's net-tie exclusion itself, and judges no candidate in Python. It chooses the spot, and counts the
refusals under the reasons, that the pure-Python sweep does."""
import math

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


def _occupancy():
    """A field of net ties round the centre of a 30 mm board, on nets the mover does not carry, and parts round it."""
    ties = [_tie("NT%d" % k, ("A", "B")) for k in range(49)]
    mover = footprint("Q", 3, 3, w=2.0, h=1.0, nets=("C", "D"))
    plain = [footprint("P%d" % k, x, y, w=3.0, h=1.0, nets=("E", "F"))
             for k, (x, y) in enumerate([(15, 21), (10, 20), (20, 20), (8, 14), (22, 14), (15, 8)])]
    occ = Occupancy(board_geometry(ties + plain + [mover], width=30, height=30), edge_margin=1.0, settings=Settings())
    for fp in plain:
        occ.commit(fp, Placement(fp.location, fp.rotation, fp.face))
    for k, t in enumerate(ties):
        occ.commit(t, Placement(Location(11.0 + 1.3 * (k % 7), 11.0 + 1.1 * (k // 7)), 0, Face.FRONT))
    return occ, mover


def _whole_face(occ, item, native, monkeypatch):
    """(chosen, tried, refusals by bucket, each bucket's reason), and how many candidates were judged in Python."""
    monkeypatch.setattr(placer, "NATIVE_SWEEP", native)
    judged = []
    real = Occupancy.legal

    def legal(self, *a, **kw):
        judged.append(1)
        return real(self, *a, **kw)
    monkeypatch.setattr(Occupancy, "legal", legal)
    box = occ.board_box
    res = placer.scan(occ, item, Placement(box.center, 0, Face.FRONT), math.hypot(box.width, box.height), 0.25,
                      rotations=(0, 90))
    reasons = {k: w.to_json() for k, w in res.reasons.items()}
    return (res.chosen, res.tried, dict(res.rejected), reasons), len(judged)


def test_an_item_among_net_ties_scanned_over_the_whole_face_takes_the_python_sweeps_spot(monkeypatch):
    occ, mover = _occupancy()
    py, _ = _whole_face(occ, mover, False, monkeypatch)
    nat, judged = _whole_face(occ, mover, True, monkeypatch)
    assert py[0] is not None, "the part has somewhere to go"
    assert sum(py[2].values()) > 10, "candidates are refused before the one chosen"
    assert judged == 0, "the native pass judged candidates in Python"
    assert nat == py
