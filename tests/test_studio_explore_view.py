"""A finished explore as the studio shows it (explore_view.py): the focused items of a run's written board gathered into one
item each, and moved from where that board has them to where the explore's best variant put them, turned and flipped as the
placer would (occupancy._transform), their 3D models with them."""
import math

from placemat import explore_view, model_place


def _fp(key, ref, poly, face="front", layers=("F.Cu",), matrix=None):
    shapes = [{"kind": "courtyard", "faces": [face], "poly": [list(p) for p in poly]},
              {"kind": "pad", "faces": [face], "layers": list(layers), "poly": [list(p) for p in poly], "net": "N", "number": "1"}]
    return {"key": key, "kind": "part", "placed": True, "members": [{"ref": ref, "inst": key, "value": "", "cell": "", "shapes": shapes,
            "models": [{"id": "m1", "state": "ok", "matrix": matrix}] if matrix else []}], "at": list(poly[0]), "rotation": 0.0, "face": face}


def _translate(x, y_height, z):
    return [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, x, y_height, z, 1.0]


def test_a_focused_items_footprints_are_gathered_into_one_item_at_its_placement():
    doc = {"items": [_fp("psu.u1", "U1", [[3, 2], [4, 2]]), _fp("other", "R9", [[0, 0], [1, 0]]), _fp("psu.c1", "C1", [[5, 2], [6, 2]]),
                     _fp("psu.sub.c2", "C2", [[7, 2], [8, 2]]), _fp("psuedo", "R8", [[9, 9], [9, 8]])]}
    out = explore_view.group_focus(doc, ["psu", "psu.sub"], {"psu": [2, 2, 0, "front"], "psu.sub": [7, 2, 90, "front"]})
    keys = [it["key"] for it in out["items"]]
    assert keys == ["psu", "other", "psu.sub", "psuedo"]                                    # in the order the board has their first footprint
    by = {it["key"]: it for it in out["items"]}
    assert [m["ref"] for m in by["psu"]["members"]] == ["U1", "C1"] and [m["ref"] for m in by["psu.sub"]["members"]] == ["C2"]   # the longest focus key wins
    assert (by["psu"]["at"], by["psu"]["rotation"], by["psu"]["face"]) == ([2, 2], 0, "front")
    assert (by["psu.sub"]["at"], by["psu.sub"]["rotation"]) == ([7, 2], 90)
    assert len(doc["items"]) == 5                                                          # the original is left alone


def test_an_item_moved_to_another_variant_turns_its_shapes_and_its_models_about_its_place():
    doc = {"items": [_fp("a", "U1", [[3, 2], [4, 2]], matrix=_translate(3, 1.5, 2)), _fp("b", "R1", [[0, 0], [1, 0]])]}
    out, moved = explore_view.move_items(doc, {"a": ([2, 2, 0, "front"], [10, 10, 90, "front"])}, thickness=1.6)
    a = out["items"][0]
    for got, want in zip(a["members"][0]["shapes"][0]["poly"], [[10, 9], [10, 8]]):       # as the page's moveShape turns it: a quarter counter-clockwise
        assert math.isclose(got[0], want[0], abs_tol=1e-9) and math.isclose(got[1], want[1], abs_tol=1e-9)
    m = a["members"][0]["models"][0]["matrix"]
    assert [round(v, 6) for v in m[12:15]] == [10, 1.5, 9]                                 # scene x is the board's x, scene z its y
    assert [round(v, 6) for v in (m[0], m[2], m[8], m[10])] == [0, -1, 1, 0]                # turned with it
    assert (a["at"], a["rotation"], a["face"]) == ([10, 10], 90, "front") and moved == ["a"]
    assert out["items"][1] == doc["items"][1] and doc["items"][0]["members"][0]["shapes"][0]["poly"] == [[3, 2], [4, 2]]


def test_an_item_that_changes_face_is_mirrored_its_copper_and_faces_swapped_and_its_models_turned_over():
    front, back = model_place.planes(1.6)
    doc = {"items": [_fp("a", "U1", [[3, 2], [4, 3]], layers=("F.Cu", "F.Mask", "In1.Cu"), matrix=_translate(3, front + 0.5, 2))]}
    out, moved = explore_view.move_items(doc, {"a": ([2, 2, 0, "front"], [10, 10, 0, "back"])}, thickness=1.6)
    a = out["items"][0]
    court, pad = a["members"][0]["shapes"]
    assert court["poly"] == [[9, 10], [8, 11]] and court["faces"] == ["back"]                # mirrored about the vertical through its place, as KiCad's F key
    assert pad["layers"] == ["B.Cu", "B.Mask", "In1.Cu"] and pad["faces"] == ["back"]
    m = a["members"][0]["models"][0]["matrix"]
    assert [round(v, 6) for v in m[12:15]] == [9, round(front + back - (front + 0.5), 6), 10]
    assert round(m[5], 6) == -1 and round(m[0], 6) == -1                                    # turned over: up is down, left is right
    assert a["face"] == "back" and moved == ["a"]


def test_an_item_the_board_or_the_variant_does_not_place_is_left_where_it_is():
    doc = {"items": [_fp("a", "U1", [[3, 2], [4, 2]])]}
    out, moved = explore_view.move_items(doc, {"a": ([2, 2, 0, "front"], None), "gone": (None, [1, 1, 0, "front"])}, thickness=1.6)
    assert moved == [] and out["items"] == doc["items"]
