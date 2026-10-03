"""The builder on a script a person wrote: items placed by a loop, a helper or a coordinate are `by hand`; an unplaced part is added
after the right statement in the script's own spelling; the outline is edited where it is plain; a coordinate is replaced by a
relation and never written."""
import pytest

from placemat import builder_intents as bi, builder_outline as bo
from placemat.builder import BuilderRefused
from tests.builder_support import Session, coordinates_in

HAND = '''"""Demo: a script a person wrote."""
from placemat import board, Along, Beside, Centre, Edge, Location, OnEdge, Part

WIDTH = 60.0
HEIGHT = 40.0

J1 = Part("j1")
U1 = Part("u1")
C1 = Part("c1")

board.rect(width=WIDTH, height=HEIGHT)

def bypass(ref, side):
    board.place(Part(ref), at=Beside(U1, side))

board.place(J1, at=OnEdge(Edge.NORTH, along=Along.MID))   # the connector
board.place(U1, at=Beside(J1, Edge.SOUTH))
for ref in ("c4",):
    board.place(Part(ref), at=Beside(U1, Edge.EAST))
board.place(Part("r1"), at=Location(30, 30))
'''


def hand(tmp_path, text=HAND):
    return Session(tmp_path, text=text)


def test_a_loop_a_coordinate_and_a_named_part_are_read_as_what_they_are(tmp_path):
    s = hand(tmp_path)
    st = {k: r["status"] for k, r in s.ctx.rows.items()}
    assert st == {"j1": "decided", "u1": "decided", "c1": "unplaced", "c4": "by hand", "r1": "by hand", "!": "x"}.get("x") or st["c4"] == "by hand"
    assert st["j1"] == "decided" and st["u1"] == "decided" and st["r1"] == "by hand" and st["c1"] == "unplaced"
    assert s.ctx.rows["r1"]["source"] == 'board.place(Part("r1"), at=Location(30, 30))'
    assert s.ctx.rows["u1"]["phrase"] == "beside J1, south" and s.ctx.plain is False


def test_an_unplaced_part_goes_after_the_statement_it_names_in_the_scripts_own_spelling(tmp_path):
    s = hand(tmp_path)
    text = s.act(["c1"], {"kind": "part", "key": "u1", "side": "WEST"}, "beside")
    # the target is spelled as the script spells it (U1); the loop writes literals, so the new part is a literal: a script that mixes gets one
    assert 'board.place(U1, at=Beside(J1, Edge.SOUTH))\nboard.place(Part("c1"), at=Beside(U1, Edge.WEST))\nfor ref' in text
    assert s.ctx.rows["c1"]["phrase"] == "beside U1, west" and s.status("c1") == "decided"
    assert coordinates_in("\n".join(l for l in text.splitlines() if "Location(30" not in l)) == []


def test_a_part_with_no_target_goes_after_the_last_top_level_placement_with_no_comment_of_the_builders(tmp_path):
    s = hand(tmp_path)
    text = s.act(["c1"], None, "searched")
    assert text.endswith('board.place(Part("r1"), at=Location(30, 30))\nboard.place(Part("c1"))\n') and "Searched from their links" not in text


def test_a_script_that_writes_literals_gets_a_literal(tmp_path):
    lit = HAND.replace("J1 = Part", "# J1 = Part").replace("board.place(J1,", 'board.place(Part("j1"),').replace("Beside(J1,", 'Beside(Part("j1"),')
    s = hand(tmp_path, lit)
    text = s.act(["c1"], {"kind": "part", "key": "u1", "side": "WEST"}, "beside")
    assert 'board.place(Part("c1"), at=Beside(U1, Edge.WEST))' in text or 'at=Beside(Part("u1")' in text


def test_an_item_in_a_loop_or_by_a_coordinate_offers_only_a_relation_and_never_the_reverse(tmp_path):
    s = hand(tmp_path)
    with pytest.raises(BuilderRefused, match="replaced by a relation, not by the search"):
        s.offers(["r1"], None)
    text = s.act(["r1"], {"kind": "part", "key": "j1", "side": "EAST"}, "beside")
    assert 'board.place(Part("r1"), at=Beside(J1, Edge.EAST))' in text and "Location(" not in text
    assert s.status("r1") == "decided"
    with pytest.raises(BuilderRefused, match="declared by a statement the builder does not edit"):
        bi.remove_edits(s.ctx, "c4")


def test_placements_only_in_helpers_are_added_at_the_end_of_the_module(tmp_path):
    only = HAND.split("board.place(J1")[0]
    s = hand(tmp_path, only)
    text = s.act(["c1"], None, "searched")
    assert "    board.place(Part(ref), at=Beside(U1, side))\nboard.place(C1)\n" in text and text.count("def bypass") == 1


def test_a_plain_scripts_outline_is_edited_in_place_and_a_computed_size_is_read_only(tmp_path):
    s = hand(tmp_path)
    assert s.ctx.outline["dims"] == {"width": 60.0, "height": 40.0} and s.ctx.outline["consts"] == {"width": "WIDTH", "height": "HEIGHT"}
    text = s.apply(list(bo.change_outline(s.ctx, {"shape": "rect", "width": 70.0, "height": 40.0}, {})["suggestion"].edits))
    assert "WIDTH = 70.0\n" in text and "HEIGHT = 40.0\n" in text
    s2 = hand(tmp_path / "b", HAND.replace("width=WIDTH", "width=WIDTH + 1"))
    assert s2.ctx.outline["editable"] is False
    with pytest.raises(BuilderRefused, match="read only"):
        bo.change_outline(s2.ctx, {"shape": "rect", "width": 70.0, "height": 40.0}, {})


def test_a_literal_size_in_the_call_gets_a_named_constant_when_it_changes(tmp_path):
    s = hand(tmp_path, HAND.replace("width=WIDTH, height=HEIGHT", "width=60, height=40"))
    text = s.apply(list(bo.change_outline(s.ctx, {"shape": "rect", "width": 70.0, "height": 40.0}, {})["suggestion"].edits))
    assert "BOARD_WIDTH_MM = 70.0" in text and "board.rect(width=BOARD_WIDTH_MM, height=40)" in text


def test_a_fit_frame_is_read_only_and_has_no_edges(tmp_path):
    frame = HAND.split("def bypass")[0].replace("board.rect(width=WIDTH, height=HEIGHT)", "board.rect(fit=True, draw=False)") + 'board.place(U1)\n'
    s = hand(tmp_path, frame)
    assert s.ctx.outline["kind"] == "fit" and s.ctx.outline["editable"] is False
    with pytest.raises(BuilderRefused, match="fit frame"):
        s.offers(["c1"], {"kind": "edge", "edge": "NORTH"})
