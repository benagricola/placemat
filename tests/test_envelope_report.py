"""What a part draws against what its courtyard says: measure's envelope line
and the run's footprints report."""
import dataclasses

import pytest

from placemat.describe import part_lines
from placemat.envelope import drawn_envelope, understatement
from placemat.layout import Board
from placemat.runner import run_metrics
from placemat.settings import Settings
from placemat.values import Location, Part
from tests.fixtures import board_geometry, footprint


def _wide():
    # courtyard 7.9..12.1 x 8.9..11.1; silk runs to 7.5 on the left, fab to 11.4 at the bottom
    return footprint("U1", 10, 10, inst="u1", silk_boxes=[(7.5, 9.0, 12.0, 9.1)], fab=(8.5, 8.8, 11.5, 11.4))


def test_the_drawn_envelope_names_the_layer_that_sets_each_side():
    box, sides = drawn_envelope(_wide())
    assert (box.left, box.top, box.right, box.bottom) == pytest.approx((7.5, 8.8, 12.0, 11.4))
    assert sides == {"left": "silk", "top": "body", "right": "silk", "bottom": "body"}


def test_measure_prints_the_envelope():
    text = "\n".join(part_lines(_wide()))
    assert "envelope 4.50 x 2.60" in text and "left silk" in text and "bottom body" in text


def test_a_courtyard_that_understates_the_part_by_more_than_the_silk_clearance_is_reported():
    assert understatement(_wide(), 0.1) == (pytest.approx(0.4), "silk")
    assert understatement(_wide(), 0.5) is None
    assert understatement(footprint("R1", 10, 10), 0.1) is None


def _plan(envelope):
    fps = [_wide(), footprint("R1", 30, 20, inst="r1")]
    b = Board(board_geometry(fps, width=50, height=40, silk_clearance=0.1), edge_margin=0.5,
              settings=dataclasses.replace(Settings(), place_envelope=envelope))
    b.place(Part("u1"), at=Location(10, 10))
    b.place(Part("r1"))
    return b.resolve()


def test_in_courtyard_mode_the_run_reports_the_footprint_and_it_is_not_a_finding():
    plan = _plan("courtyard")
    assert plan.footprints == ["U1: courtyard understates the part by 0.40 mm (silk)"]
    assert not any("understates" in f for f in plan.findings)
    assert run_metrics(plan, 2, 0, {})["footprints"] == 1


def test_in_physical_there_is_nothing_to_report():
    assert _plan("physical").footprints == []


def test_measure_json_carries_the_envelope():
    from placemat.describe import part_facts
    f = part_facts(_wide())
    assert f["envelope"] == [4.5, 2.6] and f["envelope_set_by"]["left"] == "silk"


def test_measure_json_gives_each_box_by_its_edges():
    from placemat.describe import part_facts
    f = part_facts(_wide())
    assert f["boxes"]["courtyard"] == pytest.approx([7.9, 8.9, 12.1, 11.1])
    assert f["boxes"]["envelope"] == pytest.approx([7.5, 8.8, 12.0, 11.4])
    assert set(f["boxes"]) == {"body", "courtyard", "physical", "envelope"}


def test_measure_pads_give_each_outline():
    from placemat.describe import pad_facts
    fp = _wide()
    d = pad_facts(fp, fp.pads[0])
    assert d["outline"] == [[[round(x, 4), round(y, 4)] for x, y in poly] for poly in fp.pads[0].outlines]
    assert len(d["outline"][0]) == 4
    assert d["mask_paste"] == []


def test_a_courtyard_inside_its_own_silk_or_equal_to_its_body_is_a_footprint_finding():
    from placemat.describe import part_facts, part_lines
    inside = footprint("U2", 10, 10, inst="u2", silk_boxes=[(7.0, 8.0, 13.0, 12.0)])       # silk round the courtyard
    body = footprint("U3", 10, 10, inst="u3", fab=(7.9, 8.9, 12.1, 11.1))                   # fab = courtyard
    good = footprint("U4", 10, 10, inst="u4", fab=(8.2, 9.2, 11.8, 10.8))
    assert any("inside its own silk" in s for s in part_facts(inside)["footprint_findings"])
    assert any("equals its fab body" in s for s in part_facts(body)["footprint_findings"])
    assert part_facts(good)["footprint_findings"] == []
    assert any("inside its own silk" in l for l in part_lines(inside))


def test_measure_pads_print_the_mask_and_paste_a_pad_opens():
    import dataclasses as dc
    fp = _wide()
    fp = dc.replace(fp, pads=tuple(dc.replace(p, mask_paste=("F.Mask", "F.Paste")) for p in fp.pads))
    assert any(l.rstrip().endswith("F.Mask/F.Paste") for l in part_lines(fp, pads=True))
