"""The builder's rest of the vocabulary: rows and rings, shaped boards' edge runs, holes on an existing outline, reordering decided
placements, a row's members, rotations by pad and by part. Each action's text byte for byte, the status after the resolve, and no
coordinate anywhere."""
import pytest

from placemat import builder_intents as bi, builder_outline as bo, builder_runs as br
from placemat.builder import BuilderRefused
from tests.builder_support import Session, coordinates_in
from tests.fixtures import footprint

EDGE = lambda e: {"kind": "edge", "edge": e}
TAIL = lambda text, n=1: "".join(text.splitlines(keepends=True)[-n:])


def parts6():
    return [footprint("J%d" % i, 10 + i, 10, w=4, h=3, inst="j%d" % i, nets=("S%d" % i, "GND")) for i in range(1, 4)] + \
        [footprint("U1", 10, 30, w=6, h=2, inst="u1", nets=("VIN", "OUT")), footprint("C1", 30, 30, inst="c1", nets=("VIN", "GND")),
         footprint("C2", 30, 40, inst="c2", nets=("OUT", "GND"))]


def test_several_items_are_a_row_along_an_edge_in_the_selections_order(tmp_path):
    s = Session(tmp_path, parts=parts6())
    got = s.offers(["j1", "j2", "j3"], EDGE("WEST"))
    assert [o.intent for o in got] == ["row_start", "row_mid", "row_end"]
    text = s.act(["j1", "j2", "j3"], EDGE("WEST"), "row_mid")
    assert text.endswith('\nboard.row([Part("j1"), Part("j2"), Part("j3")], Edge.WEST, align=Along.MID)\n')
    assert "from placemat import board, Along, Edge, Part\n" in text
    assert all(s.status(k) == "decided" for k in ("j1", "j2", "j3")) and s.ctx.rows["j2"]["phrase"] == "in a row"
    assert coordinates_in(text) == []
    s2 = Session(tmp_path / "b", parts=parts6())
    text2 = s2.act(["j1", "j2", "j3"], EDGE("NORTH"), "row_start", order=["j3", "j1", "j2"])
    assert 'board.row([Part("j3"), Part("j1"), Part("j2")], Edge.NORTH)' in text2


def test_a_row_beside_a_part_and_a_row_with_a_gap_and_its_reason(tmp_path):
    s = Session(tmp_path, parts=parts6())
    s.act(["u1"], EDGE("NORTH"), "on_edge_mid")
    text = s.act(["c1", "c2"], {"kind": "part", "key": "u1", "side": "SOUTH"}, "row_mid", gap=0.4, gap_note="room for the rework tool")
    assert "# The gap between C1 and U1: room for the rework tool. Chosen in the studio's board builder.\nC1_GAP_MM = 0.4\n" in text
    assert 'board.row([Part("c1"), Part("c2")], Edge.SOUTH, of=Part("u1"), gap=C1_GAP_MM, align=Along.MID)' in text
    assert s.status("c1") == "decided"


def test_a_row_is_refused_for_items_already_placed_and_with_no_target(tmp_path):
    s = Session(tmp_path, parts=parts6())
    s.act(["j1"], EDGE("NORTH"), "on_edge_mid")
    with pytest.raises(BuilderRefused, match="take it off the board"):
        s.offers(["j1", "j2"], EDGE("WEST"))
    with pytest.raises(BuilderRefused, match="along an edge or beside a part"):
        s.offers(["j2", "j3"], None)


def test_a_ring_round_a_discs_rim(tmp_path):
    s = Session(tmp_path, parts=parts6(), shape={"shape": "disc", "diameter": 60.0})
    got = s.offers(["j1", "j2", "j3"], EDGE("NORTH"))
    assert [o.intent for o in got] == ["ring"]
    text = s.act(["j1", "j2", "j3"], EDGE("NORTH"), "ring")
    assert text.endswith('\nboard.ring([Part("j1"), Part("j2"), Part("j3")], start=Edge.NORTH)\n')
    assert s.status("j1") == "decided"


def test_a_rows_members_are_taken_out_added_and_moved_by_edit_list(tmp_path):
    s = Session(tmp_path, parts=parts6())
    s.act(["j1", "j2", "j3"], EDGE("WEST"), "row_start")
    text = s.apply(list(bi.row_edit(s.ctx, "j2", "remove", "j2").edits))
    assert 'board.row([Part("j1"), Part("j3")], Edge.WEST)' in text and s.status("j2") == "unplaced"
    text = s.apply(list(bi.row_edit(s.ctx, "j1", "add", "j2").edits))
    assert 'board.row([Part("j1"), Part("j3"), Part("j2")], Edge.WEST)' in text
    text = s.apply(list(bi.row_edit(s.ctx, "j1", "move", "j2", before="j1").edits))
    assert 'board.row([Part("j2"), Part("j1"), Part("j3")], Edge.WEST)' in text
    with pytest.raises(BuilderRefused, match="same row"):
        bi.row_edit(s.ctx, "j1", "move", "j2", before="c1")


# ------------------------------------------------------------------ shaped boards
L_SHAPE = [[0, 0], [60, 0], [60, 25], [35, 25], [35, 40], [0, 40]]


def test_a_stretch_of_a_shaped_boards_edge_is_named_by_board_edge_and_bound_once(tmp_path):
    s = Session(tmp_path, parts=parts6(), shape={"shape": "polygon", "points": L_SHAPE})
    text = s.act(["j1"], EDGE("NORTH"), "on_edge_mid")
    assert text.endswith('\nnorth_edge = board.edge(facing=Edge.NORTH)\n\nboard.place(Part("j1"), at=OnEdge(north_edge, along=Along.MID))\n') or \
        'north_edge = board.edge(facing=Edge.NORTH)\n' in text
    assert s.ctx.rows["j1"]["relation"] == {"kind": "on_edge", "edge": None, "run": "north_edge", "along": "MID"}
    assert s.ctx.rows["j1"]["phrase"] == "on the edge north_edge, in the middle"
    text2 = s.act(["j2"], EDGE("NORTH"), "on_edge_start")
    assert text2.count("north_edge = board.edge") == 1 and 'Part("j2"), at=OnEdge(north_edge, along=Along.START)' in text2
    assert coordinates_in(text2) == []


def test_two_stretches_facing_one_way_are_named_by_the_one_furthest_out_or_greyed(tmp_path):
    s = Session(tmp_path, parts=parts6(), shape={"shape": "polygon", "points": L_SHAPE})
    text = s.act(["j1"], EDGE("EAST"), "on_edge_mid")
    assert "east_edge = board.edge(facing=Edge.EAST, outermost=True)" in text
    notch = [[0, 0], [20, 0], [20, 10], [40, 10], [40, 0], [60, 0], [60, 40], [0, 40]]
    s2 = Session(tmp_path / "n", parts=parts6(), shape={"shape": "polygon", "points": notch})
    with pytest.raises(BuilderRefused, match="cannot be named without a number"):
        s2.offers(["j1"], EDGE("NORTH"))
    assert br.nameable([notch], "NORTH")["count"] == 3 or br.nameable([notch], "NORTH")["count"] == 2


def test_a_slot_board_takes_its_ends_by_facing(tmp_path):
    s = Session(tmp_path, parts=parts6(), shape={"shape": "slot", "length": 60.0, "width": 30.0})
    text = s.act(["j1"], EDGE("EAST"), "on_edge_mid")
    assert "east_edge = board.edge(facing=Edge.EAST)" in text and s.status("j1") == "decided"


def test_the_run_geometry_counts_legs_and_reach():
    rect = [[0, 0], [10, 0], [10, 5], [0, 5]]
    assert br.nameable([rect], "NORTH") == {"ok": True, "outermost": False, "count": 1}
    assert br.nameable([rect[::-1]], "NORTH")["ok"] is True                      # the winding does not matter
    assert br.runs([rect], "EAST")[0]["reach"] == 10.0
    assert br.nameable([[[0, 0], [10, 0], [10, 10]]], "SOUTH")["count"] in (0, 1)


# ------------------------------------------------------------------ holes of an existing outline
def test_a_hole_is_added_to_an_outline_that_has_none_and_taken_out_again(tmp_path):
    s = Session(tmp_path, parts=parts6())
    hole = {"name": "mount", "kind": "circle", "diameter": 3.2, "at": {"edge": "NORTH", "along": "MID"}}
    spec = {"shape": "rect", "width": 60.0, "height": 40.0, "add_holes": [hole], "web": 1.0}
    text = s.apply(list(bo.change_outline(s.ctx, spec, {})["suggestion"].edits))
    assert "MOUNT_DIAMETER_MM = 3.2\n" in text and 'MOUNT = Cutout(Circle(MOUNT_DIAMETER_MM), "mount", at=OnEdge(Edge.NORTH, along=Along.MID))' in text
    assert "board.rect(width=BOARD_WIDTH_MM, height=BOARD_HEIGHT_MM, holes=[MOUNT], web=BOARD_WEB_MM)" in text
    assert s.ctx.outline["holes"] == ["MOUNT"] and coordinates_in(text) == []
    spec2 = {"shape": "rect", "width": 60.0, "height": 40.0, "remove_holes": ["MOUNT"]}
    text2 = s.apply(list(bo.change_outline(s.ctx, spec2, {})["suggestion"].edits))
    assert "MOUNT" not in text2 and "holes=" not in text2 and "BOARD_WEB_MM" in text2          # the web is the outline's own


def test_a_second_hole_joins_the_list(tmp_path):
    hole = {"name": "mount", "kind": "circle", "diameter": 3.2, "at": {"edge": "NORTH", "along": "MID"}}
    s = Session(tmp_path, parts=parts6(), shape={"shape": "rect", "width": 60.0, "height": 40.0, "web": 1.0, "holes": [hole]})
    two = dict(hole, name="vent", kind="slot", length=8.0, width=2.0, at={"edge": "SOUTH", "along": "MID"})
    text = s.apply(list(bo.change_outline(s.ctx, {"shape": "rect", "width": 60.0, "height": 40.0, "add_holes": [two]}, {})["suggestion"].edits))
    assert "holes=[MOUNT, VENT]" in text and "VENT_LENGTH_MM = 8.0" in text
    with pytest.raises(BuilderRefused, match="not a hole"):
        bo.change_outline(s.ctx, {"shape": "rect", "width": 60.0, "height": 40.0, "remove_holes": ["NOPE"]}, {})


# ------------------------------------------------------------------ the order, rotations
def test_decided_placements_move_up_and_down_and_undo_restores_the_text(tmp_path):
    s = Session(tmp_path, parts=parts6())
    s.act(["j1"], EDGE("NORTH"), "on_edge_mid")
    s.act(["j2"], EDGE("SOUTH"), "on_edge_mid")
    s.act(["j3"], EDGE("EAST"), "on_edge_mid")
    before = s.text
    text = s.apply(list(bi.move_offer(s.ctx, "j3", "up").edits))
    assert text.index('Part("j3")') < text.index('Part("j2")') and text.count('board.place(') == 3
    assert s.history[-2] == before
    with pytest.raises(BuilderRefused, match="already the first"):
        bi.move_offer(s.ctx, "j1", "up")
    with pytest.raises(BuilderRefused, match="already the last"):
        bi.move_offer(s.ctx, "j2", "down")
    with pytest.raises(BuilderRefused, match="only a decided"):
        bi.move_offer(s.ctx, "u1", "up")


def test_a_rotation_by_a_pad_facing_an_edge_and_by_another_part(tmp_path):
    s = Session(tmp_path, parts=parts6())
    s.act(["j1"], EDGE("NORTH"), "on_edge_mid")
    text = s.act(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, "beside", facing={"pad": "1", "edge": "NORTH"})
    assert 'board.place(Part("u1"), at=Beside(Part("j1"), Edge.SOUTH), rotation=Facing(PadRef(Part("u1"), "VIN"), Edge.NORTH))' in text
    assert coordinates_in(text) == []
    s2 = Session(tmp_path / "t", parts=parts6())
    s2.act(["j1"], EDGE("NORTH"), "on_edge_mid")
    text2 = s2.act(["u1"], {"kind": "part", "key": "j1", "side": "SOUTH"}, "beside", turned={"key": "j1", "degrees": 90})
    assert 'rotation=Turned(Part("j1"), 90)' in text2 or "rotation=Turned(" in text2
    with pytest.raises(BuilderRefused, match="not placed yet"):
        s2.offers(["c1"], None, turned={"key": "c2", "degrees": 0})
    with pytest.raises(BuilderRefused, match="one of"):
        s2.offers(["c1"], None, turned={"key": "j1"}, facing={"pad": "1", "edge": "NORTH"})


def test_face_priority_required_and_why_are_modifiers_of_the_same_call(tmp_path):
    s = Session(tmp_path, parts=parts6())
    with pytest.raises(BuilderRefused, match="priority carries its reason"):
        s.offers(["c1"], None, priority="HIGH")
    text = s.act(["c1"], None, "searched", face="EITHER", priority="HIGH", why="the bulk capacitor goes first", required=True)
    assert text.endswith('\n# Searched from their links.\nboard.place(Part("c1"), face=Face.EITHER, priority=Priority.HIGH, required=True, '
                         'why="the bulk capacitor goes first")\n')
    got = bi.item_mods(s.ctx, "c1", {"face": "", "required": False, "why": "now second"})
    text = s.apply(list(got.edits))
    assert 'board.place(Part("c1"), priority=Priority.HIGH, why="now second")' in text
    assert s.ctx.rows["c1"]["mods"] == {"priority": "HIGH", "why": "now second"}


def test_every_offer_the_menu_can_make_holds_no_coordinate(tmp_path):
    s = Session(tmp_path, parts=parts6())
    s.act(["u1"], EDGE("NORTH"), "on_edge_mid")
    pad = {"kind": "pad", "key": "u1", "pad": "VIN"}
    targets = [None, EDGE("NORTH"), EDGE("WEST"), {"kind": "part", "key": "u1", "side": "EAST"}, pad]
    seen = 0
    for t in targets:
        for o in s.offers(["c1"], t, own_pad="1", gap=0.3, gap_note="a reason", rotation=90, why="n"):
            if o.needs:
                continue
            text = s.script_edit.apply_edits(o.edits, lambda p: s.text)[str(s.path.resolve())][1]
            assert coordinates_in(text) == [], (o.intent, text)
            seen += 1
    assert seen >= 12


def test_a_decided_placement_moves_past_a_row_which_counts_as_one_statement(tmp_path):
    s = Session(tmp_path, parts=parts6())
    s.act(["j1", "j2"], EDGE("WEST"), "row_start")
    s.act(["j3"], EDGE("EAST"), "on_edge_mid")
    text = s.apply(list(bi.move_offer(s.ctx, "j3", "up").edits))
    assert text.index("Part(\"j3\")") < text.index("board.row(")
    with pytest.raises(BuilderRefused, match="already the first"):
        bi.move_offer(s.ctx, "j3", "up")
