"""The pin map study of a part inside a cell (a stamped module instance): the poses turn the whole cell about its centre,
every member's pads with it, round the cell's envelope; the facts name the cell, its module and its stamps, and the two
ways to take a turn (the cell turned on the board, or the module re-laid with the part turned in its frame); stamps of
one module with different best maps are said."""
import json

import pytest

from placemat import suggestions as sg
from placemat.findings import FindingCause as C
from placemat.pinmap import study_findings
from placemat.pinmap_core import study
from tests.pinmap_boards import complete, in_cell, input_of, point_pad, quad, settings, two_pad


def best_turn(inp, s):
    (g,) = study(inp, s)
    best = min(g.results, key=lambda r: r.breakdown.total)
    return best.poses[0][1]


def satellites_east():
    """U1 with A and B on its east side (its pool), their targets far west: turned alone, U1 faces them at 180 degrees.
    Four passives C1-C4 east of it, each with a net to a test point far east: in one cell with U1, turning the cell
    half round takes those four nets the long way round it."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"})
    pads += point_pad("TA", "A", -15, 12) + point_pad("TB", "B", -15, 8)
    for i in range(4):
        pads += two_pad("C%d" % (i + 1), "S%d" % i, "", 15, 8 + 1.5 * i)
        pads += point_pad("TS%d" % i, "S%d" % i, 40, 8 + 1.5 * i)
    return pads, {"U1": u1}


def test_a_part_in_a_cell_turns_with_its_cell_and_its_satellites_crossings_and_airwires_count():
    s = settings()
    pads, parts = satellites_east()
    alone, _ = input_of(pads, parts)
    assert best_turn(alone, s) == 180.0
    parts, cells = in_cell("logic", pads, parts, ["U1", "C1", "C2", "C3", "C4"])
    inp, _ = input_of(pads, parts, cells=cells)
    (part,) = inp.parts
    env = cells["logic"].envelope
    assert (part.cx, part.cy, part.hw, part.hh) == (env.center.x, env.center.y, env.width / 2, env.height / 2)
    assert {p.owner for p in part.pins} == {"", "C1", "C2", "C3", "C4"}
    assert best_turn(inp, s) == 0.0


def test_a_net_inside_the_cell_that_does_not_move_turns_with_it_and_is_not_studied():
    pads, parts = satellites_east()
    pads += two_pad("R1", "INNER", "", 14, 13)
    pads = [p for p in pads if p.ref != "U1"] + quad("U1", 10, 10, {"E": ["A", "B"], "S": ["INNER"]},
                                                     {"Pm.PinPool": "1-2"})[0]
    parts, cells = in_cell("logic", pads, parts, ["U1", "C1", "C2", "C3", "C4", "R1"])
    inp, _ = input_of(pads, parts, cells=cells)
    assert "INNER" not in {n.net for n in inp.nets} and "INNER" in {n.net for n in inp.posed}


def turned_cell():
    """U1 with A and B on its west side and their targets east of it, crossed: in a cell standing at 90 degrees with a
    passive that carries no net, U1 at 90 degrees on the board (0 in its module's frame). Half a turn wins."""
    pads, u1 = quad("U1", 10, 10, {"W": ["A", "B", ""]}, {"Pm.PinPool": "1-3"}, rotation=0.0)
    for i, net in enumerate(["A", "B"]):
        pads += point_pad("T%d" % i, net, 25, 9.5 + i)
    pads += two_pad("C1", "", "", 10, 14)
    from dataclasses import replace
    parts = {"U1": replace(u1, rotation=90.0)}
    return pads, parts


def test_a_cell_at_90_degrees_gives_both_levers_the_cell_turned_on_the_board_and_the_part_turned_in_its_module():
    pads, parts = turned_cell()
    parts, cells = in_cell("logic", pads, parts, ["U1", "C1"], rotation=90.0, module="Mcu", stamps=2)
    found, _ = study_findings(pads, parts, {}, frozenset(), {}, {}, settings(), cells=cells)
    (f,) = [f for f in found if f.cause is C.PINS_REMAP]
    facts = json.loads(json.dumps(f.facts))
    assert (facts["cell"], facts["module"], facts["stamps"]) == ("logic", "Mcu", 2)
    best = facts["rotations"][facts["best"]]
    (t,) = best["turns"]
    assert t["turn_deg"] == 180.0
    assert (t["cell"], t["cell_rotation_deg"], t["module_rotation_deg"], t["rotation_deg"]) == ("logic", 270.0, 180.0, 270.0)
    assert (facts["cell_rotation_deg"], facts["module_rotation_deg"]) == (270.0, 180.0)
    assert "turn cell logic to 270 degrees on the board" in f
    assert "re-lay module Mcu with U1 at 180 degrees in its frame" in f
    assert "next run re-places the board" in f
    assert "module Mcu's capture, which its 2 stamps share" in f
    best_advice = sg.suggest(f.cause, f.facts)[0]
    assert "turn cell logic to 270 degrees on the board" in best_advice.text
    assert "re-lay module Mcu with U1 at 180 degrees in its frame" in best_advice.text
    assert "turn U1 to" not in best_advice.text


def two_stamps():
    """Cells a and b of one module, U1 and U2 each with A-D on its east side: a's targets in the opposite order (every
    net moves), b's with only C and D crossed (two move)."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A1", "B1", "C1", "D1"]}, {"Pm.PinPool": "1-4"})
    more, u2 = quad("U2", 10, 30, {"E": ["A2", "B2", "C2", "D2"]}, {"Pm.PinPool": "1-4"})
    pads += more
    for i, net in enumerate(["D1", "C1", "B1", "A1"]):
        pads += point_pad("TA%d" % i, net, 20, 8.5 + i)
    for i, net in enumerate(["A2", "B2", "D2", "C2"]):
        pads += point_pad("TB%d" % i, net, 20, 28.5 + i)
    parts = complete(pads, {"U1": u1, "U2": u2})
    parts, a = in_cell("a", pads, parts, ["U1"], stamps=2)
    parts, b = in_cell("b", pads, parts, ["U2"], stamps=2)
    return pads, parts, dict(a, **b)


def test_stamps_of_one_module_with_different_best_maps_are_said_and_each_listed():
    pads, parts, cells = two_stamps()
    found, _ = study_findings(pads, parts, {}, frozenset(), {}, {}, settings(pins_rotations=(0.0,)), cells=cells)
    fa, fb = sorted((f for f in found if f.cause is C.PINS_REMAP), key=lambda f: f.facts["cell"])
    listed = [{"cell": "a", "ref": "U1", "moves": [{"from": "1", "to": "4"}, {"from": "2", "to": "3"},
                                                    {"from": "3", "to": "2"}, {"from": "4", "to": "1"}],
               "module_rotation_deg": 0.0},
              {"cell": "b", "ref": "U2", "moves": [{"from": "3", "to": "4"}, {"from": "4", "to": "3"}],
               "module_rotation_deg": 0.0}]
    assert fa.facts["stamp_maps"] == listed and fb.facts["stamp_maps"] == listed
    assert "the 2 stamps of module M have different best maps: a moves pins 1->4, 2->3, 3->2, 4->1 with U1 at 0 " \
           "degrees in the module's frame; b moves pins 3->4, 4->3 with U2 at 0 degrees in the module's frame" in fa


def test_stamps_of_one_module_with_the_same_best_map_say_nothing_of_it():
    pads, parts, cells = two_stamps()
    pads = [p for p in pads if not p.ref.startswith("TB")]
    for i, net in enumerate(["D2", "C2", "B2", "A2"]):
        pads += point_pad("TB%d" % i, net, 20, 28.5 + i)
    found, _ = study_findings(pads, parts, {}, frozenset(), {}, {}, settings(pins_rotations=(0.0,)), cells=cells)
    remaps = [f for f in found if f.cause is C.PINS_REMAP]
    assert len(remaps) == 2 and all("stamp_maps" not in f.facts and "different best maps" not in f for f in remaps)


def test_a_part_outside_any_cell_has_no_cell_facts():
    from tests.pinmap_boards import reversed_four
    pads, parts = reversed_four()
    found, _ = study_findings(pads, complete(pads, parts), {}, frozenset(), {}, {}, settings(pins_rotations=(0.0,)))
    (f,) = found
    assert "cell" not in f.facts and "cell" not in f.facts["rotations"][0]["turns"][0]


def cell_board(rotation=90.0):
    """U1 and a passive C1 in cell c, placed at `rotation`; four test points east."""
    from placemat.layout import Board
    from placemat.values import Cell, Location, Part
    from tests.fixtures import board_geometry, footprint
    from tests.pinmap_boards import quad_footprint
    fps = [quad_footprint("U1", 20, 20, {"E": ["A", "B", "C", "D"]}, {"Pm.PinPool": "1-4"}, inst="c.u1", cell="c"),
           footprint("C1", 20, 25, w=2, h=1, inst="c.c1", nets=("A", ""), cell="c")]
    for i, net in enumerate(["D", "C", "B", "A"]):
        fps.append(footprint("R%d" % (i + 1), 40, 17 + 2 * i, w=2, h=1, inst="r%d" % (i + 1), nets=(net, "G%d" % i)))
    b = Board(board_geometry(fps, cells=("c",), width=60, height=40), edge_margin=1.0,
              settings=settings(pins_rotations=(0.0,)))
    b.place(Cell("c"), at=Location(20, 22), rotation=rotation)
    for i in range(4):
        b.place(Part("r%d" % (i + 1)), at=Location(40, 17 + 2 * i))
    return b


def test_a_resolve_gives_the_study_each_placed_cell_its_members_envelope_and_rotation():
    from placemat.pinmap import placed_from_plan
    from placemat.values import Box
    b = cell_board()
    plan = b.resolve()
    placed = placed_from_plan(b, plan)
    c = placed.cells["c"]
    occ = plan.occupancy
    assert (c.members, c.rotation, c.face, c.flipped, c.stamps) == (("C1", "U1"), 90.0, "front", False, 1)
    assert c.envelope == Box.union([occ.courtyard_box("U1"), occ.courtyard_box("C1")])
    assert placed.parts["U1"].cell == "c" and placed.parts["R1"].cell == ""
    (f,) = [f for f in plan.findings if f.cause is C.PINS_REMAP]
    assert f.facts["cell"] == "c"


def test_a_cells_module_is_read_from_the_generators_log_beside_the_board(tmp_path):
    from dataclasses import replace
    from placemat.pinmap_input import cell_modules
    g = cell_board().geometry
    assert cell_modules(g) == {"c": (None, cell_modules(g)["c"][1])}
    (tmp_path / "layout.log").write_text(
        "DEBUG: Found module c with layout_path: package://workspace/x/modules/Mcu/layout\n"
        "DEBUG: Found module c.u1 with layout_path: None\n")
    g = replace(g, path=str(tmp_path / "layout.kicad_pcb"))
    assert cell_modules(g) == {"c": ("Mcu", "package://workspace/x/modules/Mcu/layout")}


def test_cells_of_one_module_are_counted_as_its_stamps_when_no_log_names_it():
    from dataclasses import replace
    from placemat.pinmap_input import cell_modules
    from tests.fixtures import board_geometry, footprint
    fps = [footprint("R1", 5, 5, inst="a.r", cell="a"), footprint("R2", 15, 5, inst="b.r", cell="b"),
           footprint("R3", 25, 5, inst="d.q", cell="d")]
    got = cell_modules(board_geometry(fps, cells=("a", "b", "d")))
    assert got["a"][1] == got["b"][1] != got["d"][1]


def test_a_cell_is_studied_alike_by_the_native_core_and_its_twin():
    from placemat.pinmap_core import native_core
    import pytest
    if native_core() is None:
        pytest.skip("the native module is not in use")
    pads, parts = satellites_east()
    pads += two_pad("R1", "INNER", "", 14, 13)
    parts, cells = in_cell("logic", pads, parts, ["U1", "C1", "C2", "C3", "C4", "R1"], rotation=90.0)
    inp, _ = input_of(pads, parts, quiet={"GND"}, cells=cells)
    s = settings(pins_seeds=2)
    assert study(inp, s, native=True) == study(inp, s, native=False)


def test_an_explore_line_names_the_cell_turn():
    from placemat.explore import pin_map_lines
    turn = {"ref": "U1", "turn_deg": 90.0, "rotation_deg": 90.0, "face": "front", "flip": False, "cell": "logic",
            "module": "Mcu", "stamps": 1, "cell_rotation_deg": 180.0, "module_rotation_deg": 90.0}
    report = {"pin_maps": [{"seed": 0, "score": 12.0, "seconds": 0.1, "groups": [
        {"refs": ["U1"], "present": {"weighted": 6.0}, "best": {"weighted": 2.0}, "turns": [turn]}]}]}
    assert pin_map_lines(report)[0] == ("  pin map, seed 0 at 12.0 mm: U1 6 -> 2 weighted crossings after remapping, "
                                        "with cell logic turned to 180 degrees")


def test_a_cell_turned_since_the_last_study_is_studied_again(tmp_path):
    pads, parts = turned_cell()
    cache = tmp_path / "pinmap.json"

    def run(rotation):
        p, cells = in_cell("logic", pads, dict(parts), ["U1", "C1"], rotation=rotation, module="Mcu")
        return study_findings(pads, p, {}, frozenset(), {}, {}, settings(), cache=cache, cells=cells)[1]["reused"]
    assert (run(90.0), run(90.0), run(180.0)) == (False, True, False)


def test_two_studied_parts_in_one_cell_are_studied_together_with_one_pose():
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"})
    more, u2 = quad("U2", 10, 20, {"E": ["C", "D"]}, {"Pm.PinPool": "1-2"})
    pads += more + point_pad("TA", "A", 30, 11) + point_pad("TB", "B", 30, 9)
    pads += point_pad("TC", "C", 30, 21) + point_pad("TD", "D", 30, 19)
    parts, cells = in_cell("pair", pads, {"U1": u1, "U2": u2}, ["U1", "U2"])
    inp, _ = input_of(pads, parts, cells=cells)
    (g,) = study(inp, settings())
    assert g.refs == ("U1", "U2") and g.of == 4
    assert all(len({t for _, t, _ in r.poses}) == 1 for r in g.results)


# ---- the review's fixes

def two_turned_stamps(rotation_b=90.0):
    """turned_cell twice, as cells a and b of one module: the same map and turn win in both, but U2 stands at
    `rotation_b` in its module's frame and U1 at 0, so re-laying the module cannot give both the turn they want."""
    from dataclasses import replace
    pads, parts = turned_cell()
    parts = {"U1": replace(parts["U1"], rotation=0.0)}
    more, u2 = quad("U2", 10, 40, {"W": ["A2", "B2", ""]}, {"Pm.PinPool": "1-3"})
    for i, net in enumerate(["A2", "B2"]):
        more += point_pad("T2%d" % i, net, 25, 39.5 + i)
    more += two_pad("C2", "", "", 10, 44)
    pads += more
    parts["U2"] = replace(u2, rotation=rotation_b)
    parts = complete(pads, parts)
    parts, a = in_cell("a", pads, parts, ["U1", "C1"], module="Mcu", stamps=2)
    parts, b = in_cell("b", pads, parts, ["U2", "C2"], module="Mcu", stamps=2)
    return pads, parts, dict(a, **b)


def test_stamps_whose_best_module_rotations_differ_are_flagged_each_with_its_rotation():
    pads, parts, cells = two_turned_stamps()
    found, _ = study_findings(pads, parts, {}, frozenset(), {}, {}, settings(), cells=cells)
    fa, fb = sorted((f for f in found if f.cause is C.PINS_REMAP), key=lambda f: f.facts["cell"])
    sm = fa.facts["stamp_maps"]
    assert sm == fb.facts["stamp_maps"]
    assert [(s["cell"], s["module_rotation_deg"]) for s in sm] == [("a", 180.0), ("b", 270.0)]
    assert sm[0]["moves"] == sm[1]["moves"]
    assert "a moves pins" in fa and "U1 at 180 degrees in the module's frame" in fa
    assert "U2 at 270 degrees in the module's frame" in fa


def test_the_relay_lever_says_it_relays_every_stamp():
    pads, parts, cells = two_turned_stamps()
    found, _ = study_findings(pads, parts, {}, frozenset(), {}, {}, settings(), cells=cells)
    f = next(f for f in found if f.cause is C.PINS_REMAP)
    assert "which re-lays all 2 of its stamps" in f
    assert "which re-lays all 2 of its stamps" in sg.suggest(f.cause, f.facts)[0].text


def series_in_cell():
    """U1 with A and B on its east side; R1, inside U1's cell, takes A on to AX, which runs to a test point far east;
    B runs straight to one. C1, inside the cell too, carries CAP from pool pin 3."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B", "CAP"]}, {"Pm.PinPool": "1-3"})
    pads += two_pad("R1", "A", "AX", 14, 9)
    pads += two_pad("C1", "CAP", "", 14, 12)
    pads += point_pad("TA", "AX", 30, 11) + point_pad("TB", "B", 30, 9)
    parts, cells = in_cell("logic", pads, {"U1": u1}, ["U1", "R1", "C1"])
    return pads, parts, cells


def test_a_pool_net_through_a_series_part_in_its_cell_is_followed_to_its_far_net_outside():
    pads, parts, cells = series_in_cell()
    inp, _ = input_of(pads, parts, cells=cells)
    (a,) = [n for n in inp.nets if n.net == "A"]
    assert (a.via, a.far, a.ends) == ("R1", "AX", (("U1", "1"),))
    assert [x.ref for x in a.fixed] == ["TA"]
    assert "AX" not in {n.net for n in inp.nets} and "A" in inp.part("U1").slots.movable


def test_a_pool_net_whose_far_end_is_another_member_of_its_cell_keeps_its_pin_and_is_listed():
    pads, parts, cells = series_in_cell()
    found, _ = study_findings(pads, parts, {}, frozenset(), {}, {}, settings(pins_placed_share_min=0.0), cells=cells)
    inp, _ = input_of(pads, parts, cells=cells)
    assert "CAP" not in inp.part("U1").slots.movable
    assert ("CAP", "3", "in_cell") in {(h.net, h.pin, h.why) for h in inp.part("U1").slots.held}
    (f,) = [f for f in found if f.cause is C.PINS_REMAP]
    assert f.facts["in_cell"] == [{"net": "CAP", "ref": "C1"}]


def test_an_arranged_cell_names_its_arrangement_and_the_frame_of_its_rotation():
    pads, parts = turned_cell()
    parts, cells = in_cell("logic", pads, parts, ["U1", "C1"], rotation=90.0, module="Mcu", arrangement="east")
    (f,) = [f for f in study_findings(pads, parts, {}, frozenset(), {}, {}, settings(), cells=cells)[0]
            if f.cause is C.PINS_REMAP]
    assert f.facts["arrangement"] == "east"
    assert "with U1 at 180 degrees in the frame of its arrangement east" in f


def test_a_cell_with_a_member_not_placed_is_still_studied_as_the_cell_and_lists_it():
    from placemat.pinmap import plan_findings, placed_from_plan
    b = cell_board(rotation=90.0)
    plan = b.resolve()
    plan.occupancy.pending.add("C1")
    placed = placed_from_plan(b, plan)
    assert placed.cells["c"].members == ("U1",) and placed.cells["c"].missing == ("C1",)
    b.settings = settings(pins_rotations=(0.0,), pins_placed_share_min=0.0)
    (f,) = [f for f in plan_findings(b, plan) if f.cause is C.PINS_REMAP]
    assert f.facts["cell"] == "c" and {"net": "A", "ref": "C1"} in f.facts["unplaced_ends"]


def test_a_cell_read_from_a_board_takes_its_face_from_its_members():
    from placemat.pinmap_input import placed_from_geometry
    from placemat.values import Face
    from tests.fixtures import board_geometry, footprint
    fps = [footprint("R1", 5, 5, inst="a.r", cell="a", face=Face.BACK),
           footprint("R2", 9, 5, inst="a.s", cell="a", face=Face.BACK)]
    c = placed_from_geometry(board_geometry(fps, cells=("a",))).cells["a"]
    assert (c.face, c.flipped) == ("back", True)


def test_a_group_led_by_a_loose_part_carries_the_cell_facts_of_its_member_in_a_cell():
    pads, u0 = quad("U0", 10, 30, {"E": ["J", "K"]}, {"Pm.PinPool": "1-2"})
    more, u1 = quad("U1", 10, 10, {"E": ["J", "L"]}, {"Pm.PinPool": "1-2"})
    pads += more + point_pad("TK", "K", 30, 31) + point_pad("TL", "L", 30, 9)
    parts, cells = in_cell("logic", pads, {"U0": u0, "U1": u1}, ["U1"], module="Mcu", stamps=1)
    found, _ = study_findings(pads, parts, {}, frozenset(), {}, {}, settings(pins_gain_min=0.0), cells=cells)
    (f,) = [f for f in found if f.cause is C.PINS_REMAP]
    assert f.facts["refs"] == ["U0", "U1"] and f.facts["cell"] == "logic" and f.facts["module"] == "Mcu"
    assert f.startswith("U0 and U1 in cell logic: ") and "at their present rotations" in f


def test_two_cells_turned_in_one_pose_are_each_named():
    from placemat.finding_text import render
    turn = lambda ref, cell: {"ref": ref, "turn_deg": 90.0, "rotation_deg": 90.0, "face": "front", "flip": False,
                              "cell": cell, "module": "M", "stamps": 1, "arrangement": "default",
                              "cell_rotation_deg": 90.0, "module_rotation_deg": 90.0}
    row = {"total": 1.0, "against": 0, "among": 0, "weighted": 0.0, "length_mm": 1.0, "bend_deg": 0.0, "map": [],
           "routed": [], "paths": [], "breaks": []}
    present = dict(row, total=5.0, weighted=4.0)
    facts = {"ref": "U1", "refs": ["U1", "U2"], "present": present, "best": 1, "first_map": True, "budget_out": False,
             "budget_ms": 200, "searched": 2, "of": 2, "routed": [], "present_breaks": [], "cell": "a", "module": "M",
             "stamps": 1, "rotations": [dict(row, total=5.0, weighted=4.0, turns=[]),
                                       dict(row, turns=[turn("U1", "a"), turn("U2", "b")])]}
    text = render(C.PINS_REMAP, facts)
    assert "for cell a, turn cell a to 90 degrees" in text and "for cell b, turn cell b to 90 degrees" in text
    assert "for the next" not in text


def test_a_cell_on_the_back_takes_the_turn_the_other_way_in_its_module():
    from dataclasses import replace
    pads, parts = turned_cell()
    parts = {"U1": replace(parts["U1"], rotation=90.0)}
    parts, cells = in_cell("logic", pads, parts, ["U1", "C1"], rotation=0.0, face="back", flipped=True)
    (f,) = [f for f in study_findings(pads, parts, {}, frozenset(), {}, {}, settings(), cells=cells)[0]
            if f.cause is C.PINS_REMAP]
    (t,) = f.facts["rotations"][f.facts["best"]]["turns"]
    assert t["turn_deg"] == 180.0 and (t["cell_rotation_deg"], t["module_rotation_deg"]) == (180.0, 90.0)


def test_a_cell_turned_by_the_placer_is_studied_at_the_turn_it_took():
    from placemat.pinmap import placed_from_plan
    from placemat.values import Cell, Location, Turns
    b = cell_board(rotation=0.0)
    b._intents = [i for i in b._intents if not (i.kind == "cell")]
    b.place(Cell("c"), at=Location(20, 22), rotations=Turns.ANY)
    plan = b.resolve()
    took = plan.placement("c").rotation
    assert placed_from_plan(b, plan).cells["c"].rotation == took


def test_one_reader_gives_the_fragments_and_the_module_layouts_of_a_layout_log(tmp_path):
    from placemat.describe import layout_log
    log = tmp_path / "layout.log"
    log.write_text("INFO: OPLOG PLACE_FP_FRAGMENT path=c.u1.X x=0 y=0 fragment_group=c\n"
                   "DEBUG: Found module c with layout_path: package://w/modules/Mcu/layout\n"
                   "DEBUG: Found module c.u1 with layout_path: None\n")
    got = layout_log(log)
    assert got.fragments == {"c.u1": "c"} and got.layouts == {"c": "package://w/modules/Mcu/layout"}


def rf_satellite():
    """U1 with A and B on its east side, their targets far west: turned alone, U1 faces them at 180 degrees. C1 east of
    it carries RF to an antenna far east: in one cell with U1, turning the cell half round takes RF the long way."""
    pads, u1 = quad("U1", 10, 10, {"E": ["A", "B"]}, {"Pm.PinPool": "1-2"})
    pads += point_pad("TA", "A", -15, 12) + point_pad("TB", "B", -15, 8)
    pads += two_pad("C1", "RF", "", 15, 10) + point_pad("ANT", "RF", 40, 10)
    parts, cells = in_cell("logic", pads, {"U1": u1}, ["U1", "C1"])
    return pads, parts, cells


def test_a_controlled_impedances_length_counts_impedance_weight_times_so_a_cell_turn_that_lengthens_it_loses():
    from types import SimpleNamespace
    s = settings()
    pads, parts, cells = rf_satellite()
    plain, _ = input_of(pads, parts, cells=cells)
    (g,) = study(plain, s)
    turned = next(r for r in g.results if r.poses[0][1] == 180.0)
    assert g.present.impedance_length_mm == 0.0 and best_turn(plain, s) == 180.0
    rf, _ = input_of(pads, parts, cells=cells, netclasses={"RF": SimpleNamespace(tuning_profile="z50")})
    assert next(n for n in rf.nets if n.net == "RF").controlled
    (g,) = study(rf, s)
    turned = next(r for r in g.results if r.poses[0][1] == 180.0)
    assert turned.breakdown.impedance_length_mm > g.present.impedance_length_mm + 5.0     # RF goes round the cell
    extra = s.pins_length_weight * (s.pins_impedance_weight - 1.0)
    assert g.present.total == pytest.approx(g.present.weighted + s.pins_length_weight * g.present.length_mm
                                            + s.pins_bend_weight * g.present.bend_deg
                                            + extra * g.present.impedance_length_mm)
    assert best_turn(rf, s) == 0.0


def test_a_differential_pair_half_in_a_controlled_impedance_class_is_controlled_too():
    from types import SimpleNamespace
    pads, parts, cells = rf_satellite()
    rf, _ = input_of(pads, parts, cells=cells, partners={"RF": "RF_N", "RF_N": "RF"},
                     netclasses={"RF": SimpleNamespace(tuning_profile="z90")})
    net = next(n for n in rf.nets if n.net == "RF")
    assert net.kind == "pair" and net.controlled
    assert best_turn(rf, settings()) == 0.0
