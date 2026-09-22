import pytest

from placemat.geometry import (Transform, poly_distance, polys_overlap, transform_box,
                               transform_polygon)
from placemat.values import Box, Location
from tests.fixtures import rect


def test_rotating_a_polygon_by_90_swaps_its_extents():
    poly = rect(10, 10, 4, 2)
    t = Transform.rotate_about(Location(10, 10), 90)
    box = Box.of_points(transform_polygon(poly, t))
    assert abs(box.width - 2) < 1e-9 and abs(box.height - 4) < 1e-9
    assert box.center == Location(10, 10)


def test_transform_composes_rotation_then_translation():
    t = Transform.rotate_about(Location(0, 0), 90).then(Transform.translate(5, 0))
    x, y = t.apply((1, 0))
    # KiCad's y grows downward, so a +90 rotation sends +x to -y
    assert abs(x - 5) < 1e-9 and abs(y - (-1)) < 1e-9


def test_mirroring_about_a_vertical_axis_flips_x_only():
    t = Transform.mirror_x(Location(10, 0))
    assert t.apply((12, 3)) == (8, 3)


def test_box_transform_is_the_transformed_polygon_box():
    b = Box(0, 0, 4, 2)
    assert transform_box(b, Transform.translate(1, 1)) == Box(1, 1, 5, 3)


def test_overlapping_and_separated_polygons_are_told_apart():
    a, b, c = rect(0, 0, 2, 2), rect(1, 0, 2, 2), rect(5, 0, 2, 2)
    assert polys_overlap(a, b)
    assert not polys_overlap(a, c)
    assert abs(poly_distance(a, c) - 3.0) < 1e-9
    assert poly_distance(a, b) == 0.0


def test_a_polygon_wholly_inside_another_overlaps_it():
    outer, inner = rect(0, 0, 10, 10), rect(0, 0, 1, 1)
    assert polys_overlap(outer, inner) and polys_overlap(inner, outer)


def test_distance_to_a_boundary_is_not_zero_for_a_polygon_inside_it():
    """poly_distance returns 0 when two polygons overlap, and every pad on a
    board overlaps the board outline - so it would report every pad as 0 mm
    from the edge. The measure wanted is to the boundary itself."""
    from placemat.geometry import distance_to_boundary, poly_distance
    board = ((0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0))
    pad = ((10.0, 10.0), (12.0, 10.0), (12.0, 12.0), (10.0, 12.0))
    assert poly_distance(pad, board) == 0.0                 # the trap
    assert distance_to_boundary(pad, board) == pytest.approx(10.0)


def test_it_takes_the_nearest_edge():
    from placemat.geometry import distance_to_boundary
    board = ((0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0))
    pad = ((10.0, 46.0), (12.0, 46.0), (12.0, 48.0), (10.0, 48.0))
    assert distance_to_boundary(pad, board) == pytest.approx(2.0)   # the top edge, not the left


def test_a_polygon_straddling_the_boundary_is_zero_away_from_it():
    from placemat.geometry import distance_to_boundary
    board = ((0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0))
    pad = ((-1.0, 10.0), (1.0, 10.0), (1.0, 12.0), (-1.0, 12.0))
    assert distance_to_boundary(pad, board) == pytest.approx(0.0)


def test_a_single_point_polygon_still_measures():
    """`_edges` on one point yields a degenerate segment, which
    point_segment_distance handles: no special case is needed."""
    from placemat.geometry import distance_to_boundary
    board = ((0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0))
    assert distance_to_boundary(((4.0, 10.0),), board) == pytest.approx(4.0)


def test_a_polygon_inside_another_overlaps_even_when_its_first_vertex_is_on_the_edge():
    """Containment was tested on each polygon's first vertex only. A via's
    16-gon centred 0.3 mm inside a pad's edge has that vertex exactly on the
    edge, and read as clear of a pad it sat almost wholly inside."""
    from placemat.geometry import circle_polygon, polys_overlap
    from placemat.values import Location
    pad = ((18.1, 19.5), (19.1, 19.5), (19.1, 20.5), (18.1, 20.5))
    ring = circle_polygon(Location(18.8, 20.0), 0.3)
    assert polys_overlap(ring, pad) and polys_overlap(pad, ring)


def test_polygons_that_only_touch_along_an_edge_still_do_not_overlap():
    from placemat.geometry import polys_overlap
    a = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    b = ((1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0))
    assert not polys_overlap(a, b) and not polys_overlap(b, a)
