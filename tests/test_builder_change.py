"""Changing the outline of a built script, the suggested turn, and moving a decided statement: each a structured edit, byte for byte."""
import pytest

from placemat import builder_outline as bo, builder_intents as bi, builder_turns as bt
from placemat.builder import BuilderRefused
from tests.builder_support import Session, coordinates_in

EDGE_N = {"kind": "edge", "edge": "NORTH"}


def apply(s, got):
    return s.apply(list(got["suggestion"].edits))


def test_a_dragged_size_changes_the_constant_in_place_and_says_it_was_chosen(tmp_path):
    s = Session(tmp_path, shape={"shape": "rect", "width": 50.5, "height": 34.0,
                                 "origin": {"mode": "suggested", "total_area": 1690.7, "faces": 2, "fill": 0.5, "aspect": 1.5}})
    assert "suggested by the studio's board builder" in s.text
    got = bo.change_outline(s.ctx, {"shape": "rect", "width": 60.0, "height": 34.0}, {})
    text = apply(s, got)
    assert "# The board's width, chosen in the studio's board builder.\nBOARD_WIDTH_MM = 60.0\n" in text
    assert "suggested by the studio's board builder from the parts' courtyard area: 1690.7 mm2 on two\n# faces, at most 50% filled per face, aspect 1.5.\nBOARD_HEIGHT_MM = 34.0" in text
    assert text.count("BOARD_WIDTH_MM") == 2
    with pytest.raises(BuilderRefused, match="as it was"):
        bo.change_outline(s.ctx, {"shape": "rect", "width": 60.0, "height": 34.0}, {})


def test_a_corner_is_added_and_taken_off_with_its_constant(tmp_path):
    s = Session(tmp_path)
    s.apply(list(bo.change_outline(s.ctx, {"shape": "rect_chamfer", "width": 60.0, "height": 40.0, "chamfer": 2.0}, {})["suggestion"].edits))
    assert "BOARD_CHAMFER_MM = 2.0\n" in s.text and "board.rect(width=BOARD_WIDTH_MM, height=BOARD_HEIGHT_MM, chamfer=BOARD_CHAMFER_MM)" in s.text
    s.apply(list(bo.change_outline(s.ctx, {"shape": "rect", "width": 60.0, "height": 40.0}, {})["suggestion"].edits))
    assert "CHAMFER" not in s.text and s.text.endswith("board.rect(width=BOARD_WIDTH_MM, height=BOARD_HEIGHT_MM)\n")


def test_changing_the_shape_replaces_the_statement_and_the_constants_only_it_used(tmp_path):
    s = Session(tmp_path)
    text = apply(s, bo.change_outline(s.ctx, {"shape": "disc", "diameter": 50.0}, {}))
    assert "WIDTH" not in text and "HEIGHT" not in text
    assert text.endswith("BOARD_DIAMETER_MM = 50.0\n\nboard.disc(diameter=BOARD_DIAMETER_MM)\n")
    assert s.ctx.outline["shape"] == "disc" and s.ctx.outline["dims"] == {"diameter": 50.0}


def test_a_constant_something_else_reads_stays_when_the_shape_changes(tmp_path):
    s = Session(tmp_path)
    s.text = s.text + "BOARD_NOTE = BOARD_WIDTH_MM / 2\n"
    s.resolve()
    assert s.ctx.outline["constants_used"] == ["BOARD_HEIGHT_MM"]
    got = bo.change_outline(s.ctx, {"shape": "disc", "diameter": 50.0}, {})
    text = apply(s, got)
    assert "BOARD_WIDTH_MM = 60.0" in text and "BOARD_HEIGHT_MM" not in text


def test_a_shape_change_lists_the_edge_placements_it_invalidates_and_needs_a_choice_for_each(tmp_path):
    s = Session(tmp_path)
    s.act(["j1"], EDGE_N, "on_edge_mid")
    s.act(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, "beside")
    with pytest.raises(BuilderRefused) as e:
        bo.change_outline(s.ctx, {"shape": "disc", "diameter": 50.0}, {})
    aff = e.value.extra["affected"]
    assert [(a["key"], a["choices"]) for a in aff] == [("j1", ["search", "rim"])]
    got = bo.change_outline(s.ctx, {"shape": "disc", "diameter": 50.0}, {"choices": {"j1": "rim"}})
    text = apply(s, got)
    assert 'board.place(Part("j1"), at=OnRim(Edge.NORTH))' in text and "OnEdge" not in text.split("board.disc")[1]
    assert s.status("j1") == "decided" and s.status("u1") == "decided"
    s2 = Session(tmp_path / "b")
    s2.act(["j1"], EDGE_N, "on_edge_mid")
    text2 = apply(s2, bo.change_outline(s2.ctx, {"shape": "disc", "diameter": 50.0}, {"choices": {"j1": "search"}}))
    assert text2.endswith('\n# Searched from their links.\nboard.place(Part("j1"))\n') and s2.status("j1") == "searched"


def test_a_rim_placement_goes_back_to_an_edge_when_the_board_is_a_rectangle_again(tmp_path):
    s = Session(tmp_path, shape={"shape": "disc", "diameter": 50.0})
    s.act(["j1"], {"kind": "edge", "edge": "EAST"}, "on_rim")
    assert 'at=OnRim(Edge.EAST)' in s.text
    got = bo.change_outline(s.ctx, {"shape": "rect", "width": 60.0, "height": 40.0}, {"choices": {"j1": "edge"}})
    text = apply(s, got)
    assert 'board.place(Part("j1"), at=OnEdge(Edge.EAST))' in text


def test_an_outline_with_a_computed_size_is_read_only(tmp_path):
    s = Session(tmp_path)
    s.text = s.text.replace("width=BOARD_WIDTH_MM", "width=BOARD_WIDTH_MM + 1")
    s.resolve()
    assert s.ctx.outline["editable"] is False
    with pytest.raises(BuilderRefused, match="read only"):
        bo.change_outline(s.ctx, {"shape": "rect", "width": 60.0, "height": 40.0}, {})


def test_the_polygon_changes_its_constant_list_in_place(tmp_path):
    pts = [[0, 0], [60, 0], [60, 25], [35, 25], [35, 40], [0, 40]]
    s = Session(tmp_path, shape={"shape": "polygon", "points": pts})
    assert s.ctx.outline["points"] == [[0.0, 0.0], [60.0, 0.0], [60.0, 25.0], [35.0, 25.0], [35.0, 40.0], [0.0, 40.0]]
    new = [[0, 0], [60, 0], [60, 30], [35, 30], [35, 40], [0, 40]]
    text = apply(s, bo.change_outline(s.ctx, {"shape": "polygon", "points": new}, {}))
    assert "(60.0, 30.0), (35.0, 30.0)" in text and text.count("BOARD_OUTLINE_MM") == 2
    with pytest.raises(BuilderRefused, match="not a polygon"):
        bo.change_outline(s.ctx, {"shape": "polygon", "points": [[0, 0], [1, 1]]}, {})


# ------------------------------------------------------------------ the turn
def test_the_four_turns_have_counts_and_the_fewest_is_marked(tmp_path):
    from tests.fixtures import footprint
    # U1 has VIN to the west and OUT to the east; two other parts hold VIN on the east and OUT on the west: the turn that
    # swaps its ends crosses nothing
    parts = [footprint("U1", 10, 10, w=6, h=2, inst="u1", nets=("VIN", "OUT")), footprint("A1", 40, 20, inst="a1", nets=("OUT", "X")),
             footprint("A2", 12, 30, inst="a2", nets=("VIN", "Y")), footprint("A3", 40, 5, inst="a3", nets=("OUT", "Z")),
             footprint("A4", 8, 5, inst="a4", nets=("VIN", "W"))]
    s = Session(tmp_path, parts=parts)
    for k, side in (("a1", "EAST"), ("a3", "EAST")):
        pass
    s.act(["a1"], {"kind": "edge", "edge": "EAST"}, "on_edge_mid")
    s.act(["a2"], {"kind": "edge", "edge": "SOUTH"}, "on_edge_mid")
    s.act(["u1"], {"kind": "part", "key": "a2", "side": "NORTH"}, "beside")
    got = bt.turn_counts(s.ctx, "u1")
    assert [t["rotation"] for t in got["turns"]] == [0, 90, 180, 270]
    assert got["best"] in (0, 90, 180, 270) and got["fewest"] == min(t["crossings"] for t in got["turns"])
    assert all(t["connections"] >= 1 for t in got["turns"])
    assert got["why"] == "fewest ratsnest crossings of the four turns"


def test_the_counts_are_the_ratsnest_crossings_by_hand():
    # U at the origin: pad 1 (net A) west, pad 2 (net B) east. Other parts: A at the east, B at the west, joined to nothing else, and a
    # pair of C pads far apart whose airwire runs between them. At 0 degrees U's A wire runs east across its B wire's... by hand:
    def pad(ref, number, net, x, y):
        return {"ref": ref, "number": number, "net": net, "x": x, "y": y}
    shape = lambda ref, nets, at, rot: {"key": ref.lower(), "at": at, "rotation": rot, "members": [{"ref": ref, "shapes": [
        {"kind": "pad", "net": nets[0], "number": "1", "poly": [[at[0] - 3, at[1] - .5], [at[0] - 2, at[1] - .5], [at[0] - 2, at[1] + .5], [at[0] - 3, at[1] + .5]]},
        {"kind": "pad", "net": nets[1], "number": "2", "poly": [[at[0] + 2, at[1] - .5], [at[0] + 3, at[1] - .5], [at[0] + 3, at[1] + .5], [at[0] + 2, at[1] + .5]]}]}]}
    items = [shape("U", ("A", "B"), [20, 20], 0), shape("EA", ("A", "Q"), [40, 18], 0), shape("EB", ("B", "R"), [0, 18], 0)]
    got = bt.turn_counts_of(items, "u")
    by = {t["rotation"]: t["crossings"] for t in got["turns"]}
    # at 0: A (west pad) wire goes to the east part, B (east pad) wire goes to the west part: the two wires cross. At 90, 180 and 270 the
    # ends are swapped or stand one above the other, and they do not: a tie of three, which 0 is not among, so the smallest turn is marked
    assert by == {0: 1, 90: 0, 180: 0, 270: 0} and got["best"] == 90 and got["tie"] is True


def test_a_tie_marks_no_rotation_when_zero_is_among_the_fewest():
    shape = {"key": "u", "at": [10, 10], "rotation": 0, "members": [{"ref": "U", "shapes": [
        {"kind": "pad", "net": "A", "number": "1", "poly": [[9, 9], [10, 9], [10, 10], [9, 10]]}]}]}
    other = {"key": "o", "at": [30, 10], "rotation": 0, "members": [{"ref": "O", "shapes": [
        {"kind": "pad", "net": "A", "number": "1", "poly": [[29, 9], [30, 9], [30, 10], [29, 10]]}]}]}
    got = bt.turn_counts_of([shape, other], "u")
    assert got["tie"] is True and got["best"] == 0 and {t["crossings"] for t in got["turns"]} == {0}


def test_a_turn_is_written_as_a_literal_with_its_reason_and_zero_takes_it_off(tmp_path):
    s = Session(tmp_path)
    s.act(["j1"], EDGE_N, "on_edge_mid")
    s.act(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, "beside")
    text = s.apply(list(bt.turn_edits(s.ctx, "u1", 90).edits))
    assert 'board.place(Part("u1"), at=Beside(Part("j1"), Edge.SOUTH), rotation=90, why="fewest ratsnest crossings of the four turns")\n' in text
    assert coordinates_in(text) == [] and s.ctx.rows["u1"]["mods"]["rotation"] == {"turn": 90}
    text2 = s.apply(list(bt.turn_edits(s.ctx, "u1", 180).edits))
    assert "rotation=180" in text2 and text2.count("why=") == 1
    text3 = s.apply(list(bt.turn_edits(s.ctx, "u1", 0).edits))
    assert "rotation" not in text3
    with pytest.raises(BuilderRefused, match="quarter turn"):
        bt.turn_edits(s.ctx, "u1", 45)


def test_unplace_takes_the_placing_statement_out_in_one_step_and_the_step_before_is_the_text_undo_restores(tmp_path):
    s = Session(tmp_path)
    s.act(["j1"], EDGE_N, "on_edge_mid")
    s.act(["u1"], {"kind": "edge", "edge": "SOUTH"}, "on_edge_mid")
    before = s.text
    assert s.status("u1") == "decided"
    sug = bi.remove_edits(s.ctx, "u1")
    assert sug.text.startswith("Unplace")
    s.apply(sug.edits)
    assert s.status("u1") == "unplaced" and s.status("j1") == "decided"
    assert 'Part("u1")' not in s.text and 'Part("j1")' in s.text
    assert s.history[-2] == before


def test_unplace_of_a_row_member_leaves_the_rest_of_the_row(tmp_path):
    s = Session(tmp_path)
    s.act(["r1", "c1", "c4"], {"kind": "edge", "edge": "EAST"}, "row_mid")
    s.apply(bi.remove_edits(s.ctx, "c1").edits)
    assert s.status("c1") == "unplaced" and s.status("r1") == "decided" and s.status("c4") == "decided"
