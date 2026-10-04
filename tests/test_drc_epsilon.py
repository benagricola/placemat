"""A gap short of a rule by no more than the board's DRC epsilon (`BoardGeometry.drc_epsilon`, 0.0005 mm on a fresh board) is
clear to KiCad: it takes the epsilon off a copper or hole clearance before comparing (DRC_TEST_PROVIDER_COPPER_CLEARANCE
`sub_e`) and off a hole-to-hole rule (DRC_TEST_PROVIDER_HOLE_TO_HOLE); silk and courtyard gaps are compared as they stand.
Findings and checks always judge so; placement's legality only with `[place] drc_epsilon` (default off: a nanometre)."""
import dataclasses

import pytest

from placemat.occupancy import Occupancy, Shape, hole_shape
from placemat.values import Box, CopperLayer, Face, Location
from tests.fixtures import board_geometry, footprint

CLEARANCE = 0.2
FRONT = frozenset([Face.FRONT])
TOP = frozenset([CopperLayer.F])


def _occ(epsilon=None, on=True, **geometry):
    """An occupancy that judges placement with the epsilon (`[place] drc_epsilon`) unless `on` is False."""
    from placemat.settings import Settings
    g = board_geometry([footprint("U1", 5, 5)], width=40, height=40, clearance=CLEARANCE)
    g = dataclasses.replace(g, hole_to_hole=0.25, hole_clearance=0.25, **geometry)
    if epsilon is not None:
        g = dataclasses.replace(g, drc_epsilon=epsilon)
    return Occupancy(g, edge_margin=0.0, settings=dataclasses.replace(Settings(), place_drc_epsilon=on))


def _square(x, y, side=1.0):
    poly = ((x, y), (x + side, y), (x + side, y + side), (x, y + side))
    return poly, Box.of_points(poly)


def _pads(gap):
    """Two 1 mm pads of different nets, `gap` apart."""
    (pa, ba), (pb, bb) = _square(0.0, 0.0), _square(1.0 + gap, 0.0)
    return Shape("A1", "pad", FRONT, TOP, "N1", pa, ba), Shape("B1", "pad", FRONT, TOP, "N2", pb, bb)


def test_a_gap_short_of_the_clearance_by_less_than_the_epsilon_is_clear():
    s, o = _pads(CLEARANCE - 0.0003)
    assert _occ()._conflict(s, o, None) is None


def test_a_gap_short_by_more_than_the_epsilon_is_refused():
    s, o = _pads(CLEARANCE - 0.0007)
    assert _occ()._conflict(s, o, None) is not None


def test_a_rule_no_larger_than_the_epsilon_still_asks_whether_two_things_touch():
    """`copper_through` asks whether copper is a short with a 0.1 micrometre clearance: the epsilon must not take it to nothing."""
    s, o = _pads(-0.2)                          # overlapping by 0.2 mm
    assert _occ()._conflict(s, o, 1e-4) is not None
    s, o = _pads(0.0)                           # touching
    assert _occ()._conflict(s, o, 1e-4) is not None
    s, o = _pads(0.01)                          # 10 micrometres clear
    assert _occ()._conflict(s, o, 1e-4) is None


def test_the_epsilon_is_the_boards():
    short = CLEARANCE - 0.0003
    s, o = _pads(short)
    assert _occ(epsilon=0.0)._conflict(s, o, None) is not None
    assert _occ(epsilon=0.0004)._conflict(s, o, None) is None
    s, o = _pads(CLEARANCE - 0.0007)
    assert _occ(epsilon=0.001)._conflict(s, o, None) is None


def test_a_named_clearance_takes_the_epsilon_off_too():
    s, o = _pads(0.4 - 0.0003)
    assert _occ()._conflict(s, o, 0.4) is None
    s, o = _pads(0.4 - 0.0007)
    assert _occ()._conflict(s, o, 0.4) is not None


def _hole_and_pad(gap, drill=0.5):
    """A plated hole of another net and a pad edge `gap` from its drill."""
    hole = hole_shape("H1", Location(0.0, 0.0), drill, "N1")
    pad_poly, pad_box = _square(drill / 2.0 + gap, -0.5)
    return hole, Shape("P1", "pad", FRONT, TOP, "N2", pad_poly, pad_box)


def test_a_hole_clearance_short_by_less_than_the_epsilon_is_clear():
    # the hole's drill is a polygon inscribed in its circle: the gap is taken to the circle, as the rule does
    hole, pad = _hole_and_pad(0.25 - 0.0003)
    assert _occ()._conflict(hole, pad, None) is None
    hole, pad = _hole_and_pad(0.25 - 0.0007)
    assert _occ()._conflict(hole, pad, None) is not None
    hole, pad = _hole_and_pad(0.25 - 0.0003)
    assert _occ(epsilon=0.0)._conflict(hole, pad, None) is not None


def test_a_hole_to_hole_gap_short_by_less_than_the_epsilon_is_clear():
    def holes(gap):
        a = hole_shape("H1", Location(0.0, 0.0), 0.5, "N1")
        return a, hole_shape("H2", Location(0.5 + gap, 0.0), 0.5, "N2")
    a, b = holes(0.25 - 0.0003)
    assert _occ()._conflict(a, b, None) is None
    a, b = holes(0.25 - 0.0007)
    assert _occ()._conflict(a, b, None) is not None
    a, b = holes(0.25 - 0.0003)
    assert _occ(epsilon=0.0)._conflict(a, b, None) is not None


def test_a_silk_gap_is_still_compared_as_it_stands():
    """KiCad's silk test collides at the rule itself, with no epsilon."""
    def silk(gap):
        (pa, ba), (pb, bb) = _square(0.0, 0.0), _square(1.0 + gap, 0.0)
        return Shape("A1", "silk", FRONT, frozenset(), "", pa, ba), Shape("B1", "silk", FRONT, frozenset(), "", pb, bb)
    occ = _occ()
    gap = occ.silk_clearance - 0.0003
    assert occ._conflict(*silk(gap), None) is not None


@pytest.mark.parametrize("epsilon", [0.0, 0.0005, 0.002])
def test_native_judges_as_python_does(epsilon):
    native = pytest.importorskip("placemat_native")
    from tests.test_native_conflict import _cfg_kwargs, _py_shape
    occ = _occ(epsilon=epsilon)
    cfg = _cfg_kwargs(occ)
    assert cfg["epsilon"] == epsilon
    cases = []
    for gap in (-0.2, 0.0, 0.01):
        s, o = _pads(gap)
        assert occ._conflict(s, o, 1e-4) is not None or gap > 0.0
        assert (occ._conflict(s, o, 1e-4) is not None) == native.conflict(_py_shape(s, False), _py_shape(o, False), 1e-4, **cfg)
    for short in (0.0001, 0.0003, 0.0007, 0.0015, 0.003):
        cases.append(_pads(CLEARANCE - short))
        cases.append(_hole_and_pad(0.25 - short))
        cases.append((hole_shape("H1", Location(0.0, 0.0), 0.5, "N1"),
                      hole_shape("H2", Location(0.5 + 0.25 - short, 0.0), 0.5, "N2")))
    seen = set()
    for s, o in cases:
        py = occ._conflict(s, o, None) is not None
        nat = native.conflict(_py_shape(s, False), _py_shape(o, False), None, **cfg)
        assert py == nat, (s.kind, o.kind, py, nat)
        seen.add(py)
    assert seen == ({True, False} if epsilon else {True}), "the cases must straddle the epsilon"


def _track_past_a_pad(gap, **settings):
    """A declared track of net A along y = 10 (0.2 mm wide, its edge at y 10.1) and a pad of net B whose edge is `gap` below it."""
    from placemat.layout import Board
    from placemat.settings import Settings
    from placemat.values import Net, PadRef, Part
    fps = [footprint("F1", 10, 10, w=4, h=2, inst="f1", nets=("A", "A"), excess=0.0),
           footprint("F2", 14, 10.6 + gap, w=2, h=1, inst="f2", nets=("B", "B"), excess=0.0)]
    b = Board(board_geometry(fps, width=40, height=30, clearance=CLEARANCE), edge_margin=1.0, keep_going=True,
              settings=dataclasses.replace(Settings(), **settings))
    b.place(Part("f1"), at=Location(10, 10))
    b.place(Part("f2"), at=Location(14, 10.6 + gap))
    b.track(Net("A"), [PadRef(Part("f1"), 1), Location(18.0, 10.0)], layer=CopperLayer.F, why="a track past a pad of another net")
    return b.resolve()


def _copper_findings(plan):
    return [f for f in plan.findings if str(f).startswith("copper")]


def test_the_plans_own_copper_is_a_check_and_takes_the_epsilon_with_the_setting_off():
    """The `copper.meets` finding: a declared track 0.0004 mm short of the clearance from another net's pad passes, 0.0006 short
    does not, whatever `[place] drc_epsilon` says."""
    for on in (False, True):
        assert not _copper_findings(_track_past_a_pad(CLEARANCE - 0.0004, place_drc_epsilon=on)), on
        assert _copper_findings(_track_past_a_pad(CLEARANCE - 0.0006, place_drc_epsilon=on)), on
        assert not _copper_findings(_track_past_a_pad(CLEARANCE, place_drc_epsilon=on)), on


def test_placement_judges_with_a_nanometre_unless_the_setting_is_on():
    s, o = _pads(CLEARANCE - 0.0003)
    assert _occ(on=False)._conflict(s, o, None) is not None
    assert _occ(on=True)._conflict(s, o, None) is None


def test_a_check_takes_the_epsilon_with_the_setting_off():
    off = _occ(on=False)
    s, o = _pads(CLEARANCE - 0.0003)
    assert off._conflict(s, o, None, check=True) is None
    s, o = _pads(CLEARANCE - 0.0007)
    assert off._conflict(s, o, None, check=True) is not None
    hole, pad = _hole_and_pad(0.25 - 0.0003)
    assert off._conflict(hole, pad, None) is not None
    assert off._conflict(hole, pad, None, check=True) is None
    a = hole_shape("H1", Location(0.0, 0.0), 0.5, "N1")
    b = hole_shape("H2", Location(0.5 + 0.25 - 0.0003, 0.0), 0.5, "N2")
    assert off._conflict(a, b, None) is not None
    assert off._conflict(a, b, None, check=True) is None


def test_the_net_tie_epsilon_is_the_fixed_500_nm_unless_the_setting_is_on():
    assert _occ(epsilon=0.002, on=False)._eps_nm == 500
    assert _occ(epsilon=0.002, on=True)._eps_nm == 2000


def test_native_judges_with_a_nanometre_when_the_setting_is_off():
    native = pytest.importorskip("placemat_native")
    from tests.test_native_conflict import _cfg_kwargs, _py_shape
    occ = _occ(on=False)
    cfg = _cfg_kwargs(occ)
    assert cfg["epsilon"] == 1e-9
    s, o = _pads(CLEARANCE - 0.0003)
    assert native.conflict(_py_shape(s, False), _py_shape(o, False), None, **cfg)
    assert occ._conflict(s, o, None) is not None
