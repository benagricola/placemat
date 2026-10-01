"""board.pour has no grow= or within=: a pour is a fitted polygon, never a zone grown from its pads."""
import pytest

from placemat.copper import Pour, Via, Zone
from placemat.geometry import point_in_polygon
from placemat.layout import Board
from placemat.values import CopperLayer, Location, Net, PadRef, Part
from tests.fixtures import board_geometry, footprint

F = CopperLayer.F


def _board():
    fps = [footprint("U1", 20, 20, w=4, h=2, inst="u1", nets=("A", "A")),
           footprint("U2", 30, 20, w=4, h=2, inst="u2", nets=("A", "A"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("u1"), at=Location(20, 20))
    b.place(Part("u2"), at=Location(30, 20))
    return b


def _pads():
    return [PadRef(Part("u1"), 1), PadRef(Part("u2"), 1)]


@pytest.mark.parametrize("extra", [{"grow": 1.0}, {"within": Part("u1")}, {"grow": 1.0, "within": Part("u1")}])
def test_grow_and_within_are_refused_with_the_replacement_named(extra):
    with pytest.raises(ValueError) as e:
        _board().pour(Net("A"), _pads(), layer=F, **extra)
    msg = str(e.value)
    assert "fitted" in msg and "swallow_pads=True" in msg and "board.plane(" in msg and "over=" in msg


def test_a_fitted_pour_draws_a_pour_and_no_zone():
    b = _board()
    b.pour(Net("A"), _pads(), layer=F, swallow_pads=True, why="joins the pads")
    plan = b.resolve()
    assert [op for op in plan.copper if isinstance(op, Pour)]
    assert not [op for op in plan.copper if isinstance(op, Zone)]


def test_a_stitch_over_a_fitted_pour_places_vias_inside_its_outline():
    b = _board()
    pour = b.pour(Net("A"), _pads(), layer=F, swallow_pads=True, why="joins the pads")
    b.stitch(Net("A"), pour, pitch=1.0, why="ties the pour to the inner layers")
    plan = b.resolve()
    (drawn,) = [op for op in plan.copper if isinstance(op, Pour)]
    vias = [op for op in plan.copper if isinstance(op, Via) and op.net == "A"]
    assert vias
    assert all(point_in_polygon((v.at.x, v.at.y), drawn.polygon) for v in vias)
