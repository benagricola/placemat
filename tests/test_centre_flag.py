"""`Centre(..., coordinates=)`: a numeric axis is a coordinate, and a script says so; release n warns."""
import dataclasses

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


def test_the_flag_is_off_by_default_and_a_number_is_still_accepted_in_this_release():
    c = Centre(30, 12)
    assert c.coordinates is None and not c.by_coordinates and c.numeric_axes == ("x", "y")
    assert Centre(30, 12, coordinates=True).by_coordinates and Centre(30, None).numeric_axes == ("x",)
    assert Centre(X(PadRef(Part("u1"), 3)), Y(PadRef(Part("u1"), 3))).numeric_axes == ()


def test_the_flag_is_keyword_only_and_part_of_the_value():
    with pytest.raises(TypeError):
        Centre(30, 12, None, True)
    assert Centre(30, 12) != Centre(30, 12, coordinates=True)


def test_a_centre_without_the_flag_has_the_digest_it_always_had():
    assert reuse.canonical(Centre(30, 12)) == reuse.canonical(dataclasses.replace(Centre(30, 12)))
    assert "coordinates" not in str(reuse.canonical(Centre(30, 12)))
    assert "coordinates" in str(reuse.canonical(Centre(30, 12, coordinates=True)))


def test_a_numeric_centre_gives_a_setup_warning_that_names_the_flag():
    b = _board()
    b.place(Part("u1"), at=Centre(30, 12))
    b.place(Part("c1"), at=Location(40, 40))
    b.place(Part("c4"), at=Location(40, 50))
    plan = b.resolve()
    (f,) = _found(plan, C.SETUP_CENTRE_COORDINATES)
    assert f.severity == "warning" and f.kind.value == "setup"
    assert str(f) == "u1: Centre(30, 12) places by coordinates: write coordinates=True, or place by a relation"
    assert f.facts["axes"] == ["x", "y"] and f.facts["values"] == [30, 12]


def test_one_numeric_axis_and_a_free_one_are_said_as_written():
    b = _board()
    b.place(Part("u1"), at=Centre(30, None))
    plan = b.resolve()
    (f,) = _found(plan, C.SETUP_CENTRE_COORDINATES)
    assert str(f).startswith("u1: Centre(30, None) places by coordinates")


def test_the_flag_or_references_give_no_warning():
    b = _board()
    b.place(Part("u1"), at=Centre(30, 12, coordinates=True))
    b.place(Part("c1"), at=Location(40, 40))
    b.place(Part("c4"), at=Centre(X(PadRef(Part("c1"), 1)), Y(PadRef(Part("c1"), 1))))
    assert not _found(b.resolve(), C.SETUP_CENTRE_COORDINATES)


def test_writing_the_default_flag_is_a_notice_that_says_to_leave_it_out():
    b = _board()
    b.place(Part("c1"), at=Location(40, 40))
    b.place(Part("u1"), at=Centre(X(PadRef(Part("c1"), 1)), 12, coordinates=False))
    plan = b.resolve()
    (f,) = _found(plan, C.SETUP_CENTRE_FLAG_DEFAULT)
    assert f.severity == "notice" and str(f) == "u1: coordinates=False is the default: leave it out"
