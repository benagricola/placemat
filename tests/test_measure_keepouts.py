"""measure --keepouts: each part near a keepout, its physical and courtyard
gap to it, so a keepout DRC finding against a courtyard can be told from a
part whose body is inside. Pure: synthetic boards."""
import dataclasses

from placemat.board_geometry import RuleArea
from placemat.describe import keepout_clearances, keepout_lines
from placemat.values import CopperLayer
from tests.fixtures import board_geometry, footprint, rect


def _geom():
    # R1's body box (9, 9.5)-(11, 10.5); its courtyard 0.3 mm round it. The keepout's west edge at 11.1.
    r1 = footprint("R1", 10, 10, w=2, h=1, inst="pull", courtyard_margin=0.0)
    r1 = dataclasses.replace(r1, courtyard_box=r1.phys_box.inflate(0.3))
    far = footprint("R9", 40, 40, w=2, h=1, inst="far")
    seal = RuleArea("keepout seal", None, rect(16.1, 10, 10, 10), frozenset([CopperLayer.F, CopperLayer.B]),
                    frozenset(["parts"]))
    g = board_geometry([r1, far], width=60, height=60)
    return dataclasses.replace(g, rule_areas=(seal,))


def test_a_part_whose_courtyard_crosses_but_body_clears_is_told_apart():
    (row,) = keepout_clearances(_geom(), [], near=1.0)
    assert row["keepout"] == "keepout seal" and row["ref"] == "R1" and row["instance"] == "pull"
    assert abs(row["physical"] - 0.1) < 1e-6 and row["physical_overlaps"] is False
    assert row["courtyard_overlaps"] is True
    text = "\n".join(keepout_lines(_geom(), [], near=1.0))
    assert "R1 (pull)  physical 0.100 mm  courtyard overlaps" in text, text


def test_parts_beyond_near_are_left_out_and_a_name_filters():
    assert keepout_clearances(_geom(), ["keepout other"], near=1.0) == []
    assert keepout_clearances(_geom(), [], near=0.05) == [r for r in keepout_clearances(_geom(), [], near=0.05)
                                                         if r["courtyard_overlaps"]]
