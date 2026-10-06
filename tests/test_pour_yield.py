"""A fitted pour's reach gives way to the cells the board places: a reach pour
is planned after the search, so a searched cell with a keepout keeps the spot
the board gives it, and the pour's copper, hull and reach, is cut back round
that keepout (and round every rule area that bars a fill on the pour's layer).
Where the cut leaves the pour short of its current, the neck finding names
the keepout.

Plan tests are pure (synthetic four-layer boards)."""
import dataclasses

import pytest

from placemat import checks, pourfit
from placemat.board_geometry import CopperItem, Footprint, RuleArea
from placemat.copper import Pour, Via
from placemat.geometry import polys_overlap
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, Cell, CopperLayer, Face, Location, Net, PadRef, Part, Reach
from tests.fixtures import board_geometry, declared_findings, pad, rect
from tests.test_pour_current_vias import _receptacle
from tests.test_pour_fitted import CLEARANCE

F, IN1, IN2, B = CopperLayer.F, CopperLayer.IN1, CopperLayer.IN2, CopperLayer.B
FOUR = (F, IN1, IN2, B)


@pytest.fixture(autouse=True)
def _fab_makes_every_via(monkeypatch):
    monkeypatch.setattr(Board, "fab_via_tiers", {"micro": "yes", "blind": "yes", "buried": "yes"})


def _antenna(cx, cy, keep=None, gnd_via=True):
    """Cell `ant`: one part A1 (two GND pads 1.6 mm apart) with a GND through via south of them, and a keepout that bars
    fills on every layer, as an antenna's ground clearance does: by default 4 x 2.4 mm round A1."""
    pads = (pad("A1", "ant.a1", "1", "GND", cx - 0.8, cy, 0.6, 0.6), pad("A1", "ant.a1", "2", "GND", cx + 0.8, cy, 0.6, 0.6))
    body = Box.union([p.box for p in pads])
    fp = Footprint("A1", "ant.a1", "ant", "A1", body.center, 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)
    ring = rect(cx, cy + 0.6, 0.45, 0.45)
    via = CopperItem("via", "GND", frozenset(FOUR), (ring,), Box.of_points(ring), "ant", 0.45, 0.2, ((cx, cy + 0.6),))
    keep = RuleArea("keepout ant", "ant", keep or rect(cx, cy, 4.0, 2.4), frozenset(FOUR), frozenset(["fill"]))
    return fp, ([via] if gnd_via else []), keep


def _sink():
    """U2: where the 3 A goes, one VBUS pad well away from the receptacle."""
    p = pad("U2", "u2", "6", "VBUS", 40.0, 30.0, 1.0, 1.0)
    body = p.box.inflate(0.5)
    return Footprint("U2", "u2", None, "U2", body.center, 0.0, Face.FRONT, body, body.inflate(0.1), body, (p,),
                     fields={"Pm.I": "3A"})


# The board's middle, where a cell sliding in y starts, puts A1 1.2 mm north of the via rows' hull, in the room the
# pour grows into.
HEIGHT = 2 * 18.5625


def _board(cell_at=None, ant=(12.5, 18.3), keep=None, gnd_via=True):
    fp, copper, area = _antenna(*ant, keep=keep, gnd_via=gnd_via)
    parts = [_receptacle("3A"), _sink(), fp]
    g = board_geometry(parts, cells=["ant"], copper=copper, width=60, height=HEIGHT, clearance=CLEARANCE)
    g = dataclasses.replace(g, layers=FOUR, rule_areas=(area,))
    b = Board(g, edge_margin=1.0)
    b.place(Part("j1"), at=Location(12.5, 22.5))
    b.place(Part("u2"), at=Location(40.0, 30.0))
    b.place(Cell("ant"), **(cell_at or dict(at=Location(12.5, None))))
    return b


def _pour_over_rows(b):
    j = Part("j1")
    rows = (b.vias(Net("VBUS"), along=PadRef(j, "B4A9"), count=3, size=0.6, drill=0.3),
            b.vias(Net("VBUS"), along=PadRef(j, "A4B9"), count=3, size=0.6, drill=0.3))
    b.pour(Net("VBUS"), list(rows), layer=IN2, swallow_pads=True, reach=Reach.CURRENT)


def _pours(plan):
    return [c for c in plan.copper if isinstance(c, Pour)]


def _keep_poly(plan, w=4.0, h=2.4):
    """Where the ant cell's rectangular keepout stands as placed: centred on A1's two pads."""
    a = plan.occupancy.pad_location("A1", "1")
    b = plan.occupancy.pad_location("A1", "2")
    return rect((a.x + b.x) / 2.0, (a.y + b.y) / 2.0, w, h)


def _copper(p):
    return pourfit.offset(p.points, p.stroke / 2.0)


def test_a_reach_pour_leaves_a_searched_cell_its_spot():
    alone = _board().resolve().occupancy.pad_location("A1", "1")
    b = _board()
    _pour_over_rows(b)
    plan = b.resolve()
    got = plan.occupancy.pad_location("A1", "1")
    assert (got.x, got.y) == pytest.approx((alone.x, alone.y), abs=1e-6), plan.step("ant").note
    pours = _pours(plan)
    assert pours, plan.findings
    keep = _keep_poly(plan)
    for p in pours:
        assert not polys_overlap(_copper(p), keep)
    assert not [f for f in plan.findings if "keepout ant" in f and f.startswith("pour")], plan.findings


# A keepout round the via rows but for a 1 mm slot along them, open to the east: the pour can grow only along the slot.
SLOT = ((2.0, 15.0), (24.0, 15.0), (24.0, 19.5), (4.0, 19.5), (4.0, 20.5), (24.0, 20.5), (24.0, 25.0), (2.0, 25.0))


def test_the_pour_short_of_its_current_by_a_keepout_names_it():
    b = _board(dict(at=Location(12.5, 13.0)), ant=(12.5, 13.0), keep=SLOT, gnd_via=False)
    _pour_over_rows(b)
    plan = b.resolve()
    pours = _pours(plan)
    assert pours, plan.findings
    for p in pours:
        assert not polys_overlap(_copper(p), SLOT[:4] + ((2.0, 19.5),))
    necks = [f for f in plan.findings if f.facts.get("variant") == "pour_neck"]
    assert len(necks) == 1, plan.findings
    what = necks[0].facts.get("what")
    assert what == {"form": "keepout", "name": "keepout ant", "cell": "ant"}, necks[0].facts
    assert any(f.startswith("pour VBUS: the room runs out") and "the ant cell's keepout ant stands there" in f
               for f in plan.findings), plan.findings


def test_a_keepout_that_bars_fills_cuts_the_hull_of_a_fitted_pour():
    """No reach: the fitted outline itself keeps out of a fill keepout placed before it, over the two contacts' north
    edges."""
    b = _board(dict(at=Location(12.5, 18.25)), ant=(12.5, 18.25), gnd_via=False)
    j = Part("j1")
    b.pour(Net("VBUS"), [PadRef(j, "B4A9"), PadRef(j, "A4B9")], layer=F, swallow_pads=True)
    plan = b.resolve()
    keep = _keep_poly(plan)
    pours = _pours(plan)
    assert pours, plan.findings
    for p in pours:
        assert not polys_overlap(_copper(p), keep)
