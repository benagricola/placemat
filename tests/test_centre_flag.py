"""`Centre(..., coordinates=)`: a numeric axis is a coordinate, and a script says so; a number without the flag is refused."""
import pytest

from placemat import reuse
from placemat.findings import FindingCause as C
from placemat.layout import Board
from placemat.values import Centre, Edge, Location, PadRef, Part, X, Y
from tests.fixtures import board_geometry, footprint


def _board(**kw):
    fps = [footprint("U1", 10, 10, w=6, h=2, inst="u1", nets=("VIN", "OUT")),
           footprint("C1", 40, 40, inst="c1", nets=("VIN", "GND")),
           footprint("C4", 40, 45, inst="c4", nets=("VIN", "GND"))]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True, **kw)


def _found(plan, cause):
    return [f for f in plan.findings if f.cause is cause]


def test_the_flag_is_off_by_default_and_intent_axes_need_none():
    c = Centre(X(PadRef(Part("u1"), 3)), None)
    assert c.coordinates is None and not c.by_coordinates and c.numeric_axes == ()
    assert Centre(30, 12, coordinates=True).by_coordinates and Centre(30, None, coordinates=True).numeric_axes == ("x",)
    assert Centre(X(PadRef(Part("u1"), 3)), Y(PadRef(Part("u1"), 3))).numeric_axes == ()


def test_the_flag_is_keyword_only_and_part_of_the_value():
    with pytest.raises(TypeError):
        Centre(30, 12, None, True)
    assert Centre(30, None, coordinates=True) != Centre(30, None, coordinates=True, toward=Edge.SOUTH)


def test_a_centre_without_the_flag_has_the_digest_it_always_had():
    ref = Centre(X(PadRef(Part("u1"), 3)), None)
    assert "coordinates" not in str(reuse.canonical(ref))
    assert "coordinates" in str(reuse.canonical(Centre(30, 12, coordinates=True)))


@pytest.mark.parametrize("args", [(30, 12), (30, None), (None, 12.5), (X(PadRef(Part("u1"), 3)), 12)])
def test_a_number_on_an_axis_without_the_flag_is_refused_with_what_to_write(args):
    with pytest.raises(ValueError) as e:
        Centre(*args)
    text = str(e.value)
    assert "coordinates=True" in text and "Beside" in text and "X(pad)" in text


def test_writing_the_default_flag_beside_a_number_is_refused_too():
    with pytest.raises(ValueError, match="coordinates=True"):
        Centre(30, 12, coordinates=False)


def test_the_flag_or_references_place_as_written():
    b = _board()
    b.place(Part("u1"), at=Centre(30, 12, coordinates=True))
    b.place(Part("c1"), at=Location(40, 40))
    b.place(Part("c4"), at=Centre(X(PadRef(Part("c1"), 1)), Y(PadRef(Part("c1"), 1))))
    plan = b.resolve()
    assert plan.placement("u1") is not None and plan.placement("c4") is not None


def test_writing_the_default_flag_is_a_notice_that_says_to_leave_it_out():
    b = _board()
    b.place(Part("c1"), at=Location(40, 40))
    b.place(Part("u1"), at=Centre(X(PadRef(Part("c1"), 1)), None, coordinates=False))
    plan = b.resolve()
    (f,) = _found(plan, C.SETUP_CENTRE_FLAG_DEFAULT)
    assert f.severity == "notice" and str(f) == "u1: coordinates=False is the default: leave it out"
