"""Placement keeps silk `[place] silk_margin` further than the board's silk clearance. KiCad compares silk to silk at
the rule itself, with no DRC epsilon, on geometry rounded to the nanometre (SHAPE_SEGMENT::Collide: dist_sq <
(width / 2 + clearance) ** 2, the nearest point rounded to an integer): silk placed at exactly the clearance and turned
off the quarter turns, as a stamped cell is, can come out a nanometre short."""
import dataclasses

import pytest

from placemat.occupancy import Occupancy, Shape
from placemat.settings import Settings
from placemat.values import Box, Face
from tests.fixtures import board_geometry, footprint

SILK = 0.2
FRONT = frozenset([Face.FRONT])


def _occ(**settings):
    g = board_geometry([footprint("U1", 5, 5)], width=40, height=40, silk_clearance=SILK)
    return Occupancy(g, edge_margin=0.0, settings=dataclasses.replace(Settings(), **settings))


def _silk(gap):
    """Two 1 mm silk squares of two parts, `gap` apart."""
    a = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    b = tuple((x + 1.0 + gap, y) for x, y in a)
    return (Shape("A1", "silk", FRONT, frozenset(), "", a, Box.of_points(a)),
            Shape("B1", "silk", FRONT, frozenset(), "", b, Box.of_points(b)))


def test_silk_at_exactly_the_clearance_is_refused():
    assert _occ()._conflict(*_silk(SILK), None) is not None


def test_silk_the_margin_past_the_clearance_is_clear():
    margin = Settings().place_silk_margin
    assert margin > 0.0
    assert _occ()._conflict(*_silk(SILK + margin), None) is None
    assert _occ()._conflict(*_silk(SILK + margin * 0.5), None) is not None


def test_the_margin_is_a_setting():
    assert _occ(place_silk_margin=0.0)._conflict(*_silk(SILK), None) is None
    assert _occ(place_silk_margin=0.01)._conflict(*_silk(SILK + 0.005), None) is not None


def test_the_refusal_names_the_gap_placement_keeps():
    why = _occ()._conflict(*_silk(SILK), None)
    assert why.facts["need_mm"] == pytest.approx(SILK + Settings().place_silk_margin)


def test_native_judges_silk_as_python_does():
    native = pytest.importorskip("placemat_native")
    from tests.test_native_conflict import _cfg_kwargs, _py_shape
    occ = _occ()
    cfg = _cfg_kwargs(occ)
    margin = Settings().place_silk_margin
    seen = set()
    for gap in (SILK - margin, SILK, SILK + margin * 0.5, SILK + margin, SILK + 2 * margin):
        s, o = _silk(gap)
        py = occ._conflict(s, o, None) is not None
        assert py == native.conflict(_py_shape(s, False), _py_shape(o, False), None, **cfg), gap
        seen.add(py)
    assert seen == {True, False}


def _pair_board():
    """U1 draws a silk line along its north side (top y 18.8); R1 draws one along its south side, 0.2 mm off its body."""
    from placemat.layout import Board
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "B"), excess=0.0, silk_boxes=[(18.0, 18.8, 22.0, 18.9)]),
           footprint("R1", 40, 40, w=2, h=1.3, inst="r1", nets=("A", "GND"), excess=0.0,
                     silk_boxes=[(39.0, 40.85, 41.0, 40.95)])]
    return Board(board_geometry(fps, width=60, height=60, silk_clearance=SILK), edge_margin=1.0,
                 settings=dataclasses.replace(Settings(), place_envelope="physical"), component_spacing=SILK)


def test_a_place_the_script_decided_is_judged_at_the_boards_own_clearance():
    """R1 decided with its silk exactly the clearance from U1's: as KiCad judges it, no collision."""
    from placemat.values import Location, Part
    b = _pair_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Location(20, 18.8 - SILK - 0.95 + 0.0))        # R1's silk bottom at 18.6
    plan = b.resolve()
    assert not plan.findings, plan.findings


def test_a_place_placement_chooses_keeps_the_margin():
    from placemat.values import Beside, Edge, Part, Location
    b = _pair_board()
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("r1"), at=Beside(Part("u1"), Edge.NORTH))
    plan = b.resolve()
    silk = [s for s in plan.occupancy.items["R1"].shapes if s.kind == "silk"]
    assert max(s.box.bottom for s in silk) <= 18.8 - SILK - Settings().place_silk_margin + 1e-6
