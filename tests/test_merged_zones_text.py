"""What a run says of the cell zones its write merged into the board's
planes, and the containment test the merge rests on."""
from placemat.geometry import poly_within
from placemat.layout import MergedZone
from placemat.runner import _merged_by_cell
from placemat.values import CopperLayer

SQUARE = ((0, 0), (10, 0), (10, 10), (0, 10))


def test_a_polygon_inside_another_is_within_it():
    assert poly_within(((2, 2), (4, 2), (4, 4), (2, 4)), SQUARE)


def test_a_polygon_across_the_edge_is_not_within():
    assert not poly_within(((8, 2), (12, 2), (12, 4), (8, 4)), SQUARE)


def test_a_polygon_across_a_concave_notch_is_not_within():
    notched = ((0, 0), (10, 0), (10, 10), (6, 10), (6, 4), (4, 4), (4, 10), (0, 10))
    assert not poly_within(((2, 6), (8, 6), (8, 8), (2, 8)), notched)


def test_one_line_per_cell_names_each_net_and_its_layers():
    merged = [MergedZone("logic", "GND", CopperLayer.IN1), MergedZone("logic", "GND", CopperLayer.IN4),
              MergedZone("logic", "V3V3", CopperLayer.IN3), MergedZone("status", "GND", CopperLayer.IN1,
                                                                        "its pads were thermal, the plane's are solid")]
    assert _merged_by_cell(merged) == [
        ("logic", "GND on In1.Cu, In4.Cu; V3V3 on In3.Cu"),
        ("status", "GND on In1.Cu (its pads were thermal, the plane's are solid)")]
