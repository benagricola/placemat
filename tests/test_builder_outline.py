"""The builder's outline: the skeleton for each shape written byte for byte, the size suggestion, the polygon's checks, and that each
script resolves on a synthetic board."""
import math

import pytest

from placemat import builder as b
from tests.builder_support import coordinates_in, golden, run_text

SPECS = {
    "rect": {"shape": "rect", "width": 60.0, "height": 40.0},
    "rect_suggested": {"shape": "rect", "width": 50.5, "height": 34.0,
                       "origin": {"mode": "suggested", "total_area": 1690.7, "faces": 2, "fill": 0.5, "aspect": 1.5}},
    "chamfer": {"shape": "rect_chamfer", "width": 60.0, "height": 40.0, "chamfer": 2.0},
    "round": {"shape": "rect_round", "width": 60.0, "height": 40.0, "radius": 3.0},
    "disc": {"shape": "disc", "diameter": 50.0},
    "bore": {"shape": "disc_bore", "diameter": 50.0, "bore": 6.0},
    "slot": {"shape": "slot", "length": 60.0, "width": 30.0},
    "polygon": {"shape": "polygon", "points": [[0, 0], [60, 0], [60, 25], [35, 25], [35, 40], [0, 40]]},
    "hole": {"shape": "rect", "width": 60.0, "height": 40.0, "web": 1.0,
             "holes": [{"name": "mount", "kind": "circle", "diameter": 3.2, "at": {"edge": "NORTH", "along": "MID"}}]},
    "disc_hole": {"shape": "disc", "diameter": 50.0,
                  "holes": [{"name": "vent", "kind": "slot", "length": 8.0, "width": 2.0, "at": {"bearing": "EAST", "radius": 15.0}}]},
}


@pytest.mark.parametrize("name", sorted(SPECS))
def test_the_skeleton_for_each_outline_is_written_byte_for_byte(name):
    assert b.new_script("Demo", "layout.", SPECS[name]) == golden("skeleton_%s.txt" % name)


@pytest.mark.parametrize("name", sorted(SPECS))
def test_each_skeleton_resolves_and_holds_no_coordinate(tmp_path, name):
    text = b.new_script("Demo", "layout.", SPECS[name])
    assert coordinates_in(text) == []
    _board, _plan, doc, _ = run_text(tmp_path, text)
    assert doc["board"]["loops"]
    assert not [f for f in doc["findings"] if "outside" in f["text"] or "cutout" in f["text"]]


def test_a_skeleton_with_no_description_names_the_board_and_says_layout():
    assert b.new_script("Demo", "", SPECS["rect"]).startswith('"""Demo layout."""\n')


def test_the_spec_example_skeleton_is_exact():
    assert golden("skeleton_rect.txt") == '''"""Demo: layout."""
from placemat import board

# The board's width, chosen in the studio's board builder.
BOARD_WIDTH_MM = 60.0
# The board's height, chosen in the studio's board builder.
BOARD_HEIGHT_MM = 40.0

board.rect(width=BOARD_WIDTH_MM, height=BOARD_HEIGHT_MM)
'''
    assert "# The board's width, suggested by the studio's board builder from the parts' courtyard area: 1690.7 mm2 on two\n" \
           "# faces, at most 50% filled per face, aspect 1.5.\nBOARD_WIDTH_MM = 50.5\n" in golden("skeleton_rect_suggested.txt")


def test_a_hole_at_the_start_of_an_edge_is_refused_because_it_would_reach_past_the_corner():
    spec = dict(SPECS["hole"], holes=[dict(SPECS["hole"]["holes"][0], at={"edge": "NORTH", "along": "START"})])
    with pytest.raises(b.BuilderRefused, match="reaches past the corner"):
        b.outline_edits('"""x"""\nfrom placemat import board\n', spec, "f.py")


def test_a_name_the_script_binds_gets_a_counter_not_an_overwrite():
    head = '"""x"""\nfrom placemat import board\nBOARD_WIDTH_MM = 1\n'
    edits = b.outline_edits(head, SPECS["rect"], "f.py")
    assert [e.args["name"] for e in edits if e.op == "set_constant"] == ["BOARD_WIDTH_MM_2", "BOARD_HEIGHT_MM"]


# ------------------------------------------------------------------ sizes
def test_the_suggested_rectangle_follows_the_formula_and_rounds_up_to_the_grid():
    s = b.suggest_size(1690.7, 2, 0.5, 1.5, "rect", 0.5)
    area = 1690.7 / (2 * 0.5)
    w = math.sqrt(area * 1.5)
    assert s["area"] == pytest.approx(area) and (s["width"], s["height"]) == (50.5, 34.0)
    assert s["width"] >= w and s["width"] - w < 0.5 and s["height"] >= area / w
    one = b.suggest_size(1690.7, 1, 0.5, 1.5, "rect", 0.5)
    assert one["area"] == pytest.approx(2 * area) and one["width"] > s["width"]
    assert b.suggest_size(100.0, 1, 0.25, 1.0, "rect", 1.0) == dict(b.suggest_size(100.0, 1, 0.25, 1.0, "rect", 1.0), width=20.0, height=20.0)


def test_the_suggested_disc_and_slot():
    d = b.suggest_size(1000.0, 1, 0.5, 1.0, "disc", 0.5)
    assert d["diameter"] == pytest.approx(math.ceil(math.sqrt(4 * 2000.0 / math.pi) / 0.5) * 0.5)
    sl = b.suggest_size(1000.0, 1, 0.5, 1.0, "slot", 0.5, slot_aspect=2.0)
    area = b.shape_area({"shape": "slot", "length": sl["length"], "width": sl["width"]})
    assert area >= 2000.0 and area < 2000.0 * 1.1 and sl["length"] / sl["width"] == pytest.approx(2.0, rel=0.05)


def test_a_polygon_template_scales_its_dimensions_together_to_the_area():
    s = b.suggest_size(1000.0, 1, 0.5, 1.0, "polygon", 0.5, template={"kind": "l_shape"})
    area = b.shape_area({"shape": "polygon", "points": s["points"]})
    assert 2000.0 <= area < 2000.0 * 1.06
    ratio = s["dims"]["height"] / s["dims"]["width"]
    assert ratio == pytest.approx(0.8, abs=0.03)
    with pytest.raises(b.BuilderRefused, match="free vertex list"):
        b.suggest_size(1000.0, 1, 0.5, 1.0, "polygon", 0.5)


def test_a_typed_size_shows_the_resulting_fill():
    spec = {"shape": "rect", "width": 50.0, "height": 40.0}
    assert b.resulting_fill(1000.0, 2, spec) == pytest.approx(1000.0 / (2 * 2000.0))
    assert b.resulting_fill(1000.0, 1, {"shape": "disc", "diameter": 40.0}) == pytest.approx(1000.0 / (math.pi * 400.0))


def test_the_suggestion_refuses_what_it_cannot_size():
    with pytest.raises(b.BuilderRefused, match="one face or two"):
        b.suggest_size(100.0, 3, 0.5, 1.0, "rect", 0.5)
    with pytest.raises(b.BuilderRefused, match="fill"):
        b.suggest_size(100.0, 1, 0.0, 1.0, "rect", 0.5)
    with pytest.raises(b.BuilderRefused, match="courtyard"):
        b.suggest_size(0.0, 1, 0.5, 1.0, "rect", 0.5)


def test_every_template_is_a_valid_polygon():
    for kind in b.TEMPLATES:
        pts = b.template_scale(kind, 1500.0, 0.5)["points"]
        assert b.polygon_problems(pts) == []


def test_a_polygon_is_refused_when_it_is_not_a_shape():
    assert "three vertices" in b.polygon_problems([[0, 0], [1, 1]])[0]
    assert "repeated" in b.polygon_problems([[0, 0], [10, 0], [10, 0], [0, 10]])[0]
    assert "no area" in b.polygon_problems([[0, 0], [5, 0], [10, 0]])[0]
    assert any("cross" in p for p in b.polygon_problems([[0, 0], [10, 0], [2, 8], [12, 8]]))
    assert b.polygon_problems([[0, 0], [10, 0], [10, 10], [0, 10]]) == []
    with pytest.raises(b.BuilderRefused, match="not a polygon"):
        b.outline_edits('"""x"""\nfrom placemat import board\n', {"shape": "polygon", "points": [[0, 0], [1, 1]]}, "f.py")


@pytest.mark.parametrize("spec, why", [
    ({"shape": "rect", "width": 0, "height": 10}, "positive"),
    ({"shape": "rect_chamfer", "width": 10, "height": 10, "chamfer": 6}, "half the shorter"),
    ({"shape": "rect_round", "width": 10, "height": 10}, "half the shorter"),
    ({"shape": "disc_bore", "diameter": 10, "bore": 10}, "under the diameter"),
    ({"shape": "slot", "length": 5, "width": 5}, "longer"),
    ({"shape": "star"}, "not an outline shape"),
    ({"shape": "rect", "width": 10, "height": 10, "holes": [{"name": "m", "kind": "circle", "diameter": 3, "at": {"edge": "NORTH"}}]}, "web"),
    ({"shape": "rect", "width": 10, "height": 10, "holes": [{"name": "m", "kind": "circle", "diameter": 3, "at": {"bearing": "EAST", "radius": 2}}]}, "placed at an edge"),
])
def test_an_outline_that_is_not_one_is_refused_with_its_rule(spec, why):
    with pytest.raises(b.BuilderRefused, match=why):
        b.outline_edits('"""x"""\nfrom placemat import board\n', spec, "f.py")
