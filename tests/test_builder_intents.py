"""The builder's intents on a synthetic board: each action as data, the script text it writes byte for byte, the status the part has after
the resolve, and that no coordinate is ever written."""
import pytest

from placemat import builder_intents as bi
from placemat.builder import BuilderRefused
from tests.builder_support import Session, coordinates_in

EDGE_N = {"kind": "edge", "edge": "NORTH"}
HEAD = '''"""Demo: layout."""
from placemat import board, %s

# The board's width, chosen in the studio's board builder.
BOARD_WIDTH_MM = 60.0
# The board's height, chosen in the studio's board builder.
BOARD_HEIGHT_MM = 40.0

board.rect(width=BOARD_WIDTH_MM, height=BOARD_HEIGHT_MM)
'''


def test_a_part_goes_on_an_edge_in_the_middle_and_is_decided(tmp_path):
    s = Session(tmp_path)
    assert {r["key"]: r["status"] for r in s.ctx.listing["rows"]} == {k: "unplaced" for k in ("u1", "c1", "c4", "r1", "j1")}
    text = s.act(["j1"], EDGE_N, "on_edge_mid")
    assert text == HEAD % "Along, Edge, OnEdge, Part" + '\nboard.place(Part("j1"), at=OnEdge(Edge.NORTH, along=Along.MID))\n'
    assert s.status("j1") == "decided"
    row = s.ctx.rows["j1"]
    assert row["relation"] == {"kind": "on_edge", "edge": "NORTH", "run": None, "along": "MID"} and row["phrase"] == "on the north edge, in the middle"
    assert coordinates_in(text) == []


def test_the_edge_menu_has_somewhere_start_middle_end(tmp_path):
    s = Session(tmp_path)
    assert [o.intent for o in s.offers(["j1"], EDGE_N)] == ["on_edge_any", "on_edge_start", "on_edge_mid", "on_edge_end"]
    s.act(["j1"], EDGE_N, "on_edge_any")
    assert 'at=OnEdge(Edge.NORTH))' in s.text


def test_a_part_goes_beside_a_placed_part_after_it_in_the_file(tmp_path):
    s = Session(tmp_path)
    s.act(["j1"], EDGE_N, "on_edge_mid")
    text = s.act(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, "beside")
    assert text.endswith('board.place(Part("j1"), at=OnEdge(Edge.NORTH, along=Along.MID))\n'
                         'board.place(Part("u1"), at=Beside(Part("j1"), Edge.SOUTH))\n')
    assert "from placemat import board, Along, Beside, Edge, OnEdge, Part\n" in text
    assert s.ctx.rows["u1"]["phrase"] == "beside J1, south" and s.status("u1") == "decided"


def test_a_gap_is_a_named_constant_with_the_users_reason(tmp_path):
    s = Session(tmp_path)
    s.act(["j1"], EDGE_N, "on_edge_mid")
    with pytest.raises(BuilderRefused, match="reason"):
        s.offers(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, gap=0.5)
    text = s.act(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, "beside", gap=0.5, gap_note="the connector's shell is tall")
    assert "# The gap between U1 and J1: the connector's shell is tall. Chosen in the studio's board builder.\nU1_GAP_MM = 0.5\n" in text
    assert 'at=Beside(Part("j1"), Edge.SOUTH, gap=U1_GAP_MM))' in text
    assert coordinates_in(text) == []
    assert s.ctx.rows["u1"]["relation"]["gap"] == {"const": "U1_GAP_MM"}


def test_the_rest_is_searched_in_one_block_with_one_comment(tmp_path):
    s = Session(tmp_path)
    s.act(["j1"], EDGE_N, "on_edge_mid")
    sug = bi.search_rest(s.ctx)
    assert sug["keys"] == ["c1", "c4", "r1", "u1"]
    text = s.apply(list(sug["suggestion"].edits))
    assert text.endswith('\n# Searched from their links.\nboard.place(Part("c1"))\nboard.place(Part("c4"))\nboard.place(Part("r1"))\nboard.place(Part("u1"))\n')
    assert all(s.status(k) == "searched" for k in ("c1", "c4", "r1", "u1")) and s.status("j1") == "decided"
    with pytest.raises(BuilderRefused, match="nothing is left"):
        bi.search_rest(s.ctx)


def test_a_searched_part_becomes_decided_by_the_move_into_the_decided_region(tmp_path):
    s = Session(tmp_path)
    s.act(["j1"], EDGE_N, "on_edge_mid")
    s.apply(list(bi.search_rest(s.ctx)["suggestion"].edits))
    text = s.act(["c4"], {"kind": "part", "key": "j1", "side": "EAST"}, "beside")
    assert text.index('Part("c4"), at=Beside(Part("j1"), Edge.EAST)') < text.index("# Searched from their links.")
    assert text.count('Part("c4")') == 1 and s.status("c4") == "decided"


def test_a_decided_part_becomes_searched_again_by_the_move(tmp_path):
    s = Session(tmp_path)
    s.act(["j1"], EDGE_N, "on_edge_mid")
    s.act(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, "beside")
    text = s.act(["u1"], None, "searched")
    assert text.endswith('board.place(Part("j1"), at=OnEdge(Edge.NORTH, along=Along.MID))\n\n# Searched from their links.\nboard.place(Part("u1"))\n')
    assert s.status("u1") == "searched"


def test_a_decided_part_given_another_relation_is_changed_in_place(tmp_path):
    s = Session(tmp_path)
    s.act(["j1"], EDGE_N, "on_edge_mid")
    s.act(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, "beside")
    before = s.text
    text = s.act(["u1"], {"kind": "part", "key": "j1", "side": "EAST"}, "beside")
    assert text == before.replace("Edge.SOUTH))\n", "Edge.EAST))\n") and s.ctx.rows["u1"]["relation"]["side"] == "EAST"


def test_taking_an_item_off_removes_its_statement_and_a_constant_only_it_used(tmp_path):
    s = Session(tmp_path)
    s.act(["j1"], EDGE_N, "on_edge_mid")
    s.act(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, "beside", gap=0.5, gap_note="room for the shell")
    sug = bi.remove_edits(s.ctx, "u1")
    text = s.apply(list(sug.edits))
    assert "U1_GAP_MM" not in text and 'Part("u1")' not in text and s.status("u1") == "unplaced"


def test_a_target_must_be_placed_and_must_not_depend_on_the_subject(tmp_path):
    s = Session(tmp_path)
    with pytest.raises(BuilderRefused, match="not placed yet"):
        s.offers(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"})
    s.act(["j1"], EDGE_N, "on_edge_mid")
    s.act(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, "beside")
    with pytest.raises(BuilderRefused, match="placed by a relation to J1"):
        s.offers(["j1"], {"kind": "part", "key": "u1", "side": "EAST"})
    with pytest.raises(BuilderRefused, match="itself|by itself"):
        s.offers(["j1"], {"kind": "part", "key": "j1", "side": "EAST"})
    with pytest.raises(BuilderRefused, match="choose a side"):
        s.offers(["c1"], {"kind": "part", "key": "j1"})


def test_a_pad_offers_beside_level_close_to_or_near_and_in_line(tmp_path):
    s = Session(tmp_path)
    s.act(["u1"], EDGE_N, "on_edge_mid")
    got = s.offers(["c1"], {"kind": "pad", "key": "u1", "pad": "VIN"})
    assert [o.intent for o in got] == ["beside_pad_side", "beside_level", "close_to_pad", "in_line_x", "in_line_y"]
    close = next(o for o in got if o.intent == "close_to_pad")
    assert close.needs == [] or close.needs == ["own_pad"]
    text = s.act(["c1"], {"kind": "pad", "key": "u1", "pad": "VIN"}, "close_to_pad")
    assert text.endswith('\n# Searched from their links.\nboard.link(PadRef(Part("c1"), "VIN"), PadRef(Part("u1"), "VIN"), weight=LinkWeight.SHORT)\n'
                         'board.place(Part("c1"))\n')
    assert coordinates_in(text) == []
    assert s.status("c1") == "searched"


def test_a_part_sharing_no_net_with_the_pad_is_placed_near_it_not_linked(tmp_path):
    from tests.fixtures import footprint
    parts = [footprint("U1", 10, 10, w=6, h=2, inst="u1", nets=("A", "B")), footprint("C9", 40, 40, inst="c9", nets=("X", "Y")),
             footprint("C8", 40, 45, inst="c8", nets=("A", "Y"))]
    s = Session(tmp_path, parts=parts)
    s.act(["u1"], EDGE_N, "on_edge_mid")
    got = s.offers(["c9"], {"kind": "pad", "key": "u1", "pad": "A"})
    assert "near_pad" in [o.intent for o in got] and "close_to_pad" not in [o.intent for o in got]
    got8 = s.offers(["c8"], {"kind": "pad", "key": "u1", "pad": "A"})
    assert "close_to_pad" in [o.intent for o in got8] and "near_pad" not in [o.intent for o in got8]
    text = s.act(["c9"], {"kind": "pad", "key": "u1", "pad": "A"}, "near_pad")
    assert text.endswith('board.place(Part("c9"), at=Near(PadRef(Part("u1"), "A")))\n') or 'Near(PadRef(Part("u1"), "A"))' in text
    assert s.status("c9") == "searched" and coordinates_in(text) == []
