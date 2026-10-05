"""The pin map study of a part inside a cell (a stamped module instance): the poses turn the whole cell about its centre,
every member's pads with it, round the cell's envelope; the facts name the cell, its module and its stamps, and the two
ways to take a turn (the cell turned on the board, or the module re-laid with the part turned in its frame); stamps of
one module with different best maps are said."""
import json

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
                                                    {"from": "3", "to": "2"}, {"from": "4", "to": "1"}]},
              {"cell": "b", "ref": "U2", "moves": [{"from": "3", "to": "4"}, {"from": "4", "to": "3"}]}]
    assert fa.facts["stamp_maps"] == listed and fb.facts["stamp_maps"] == listed
    assert "the 2 stamps of module M have different best maps: a moves pins 1->4, 2->3, 3->2, 4->1; " \
           "b moves pins 3->4, 4->3" in fa


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
