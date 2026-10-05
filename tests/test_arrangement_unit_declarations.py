"""board.unit and its options, board.exclude, the units' order, and the checks made where the script finishes declaring."""
import dataclasses

import pytest

from placemat import Alt, arrangement_run as run
from placemat.arrangements import Group, GroupOption
from placemat.layout import Board, DeclaredGroup
from placemat.settings import Settings
from placemat.values import Beside, CopperLayer, Edge, Location, Net, PadRef, Part
from tests.arrangement_support import module, parts
from tests.fixtures import board_geometry

HERE = "test_arrangement_unit_declarations.py:"


def paired(settings=None):
    b = module(settings)
    return b, b.unit("pair", Part("c_in"), Part("r_pull"), why="the pair moves as one")


def declared():
    """r_pull with its own option; a unit of c_in with two options; a board.arrangement that moves r_pull too."""
    b = module(dataclasses.replace(Settings(), place_arrangements_max=20))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    cap = b.unit("cap", Part("c_in"), why="the bypass may stand north or south of u1")
    b.alternative(cap, "north", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)))
    b.alternative(cap, "south", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.SOUTH)))
    b.arrangement("lifted", Alt(Part("r_pull"), at=Beside(Part("u1"), Edge.NORTH)), why="the pull-up north")
    return b


def test_board_group_still_writes_a_kicad_group_and_takes_no_option():
    """Review focus 2: board.group is unchanged; the unit is board.unit."""
    b = module()
    kept = b.group("kept", [Part("c_in"), Part("r_pull")], why="moved as one by hand")
    assert isinstance(kept, DeclaredGroup) and "kept" in b._groups and b._arr_groups == []
    pair = b.unit("pair", Part("c_in"), Part("r_pull"), why="the pair moves as one")
    assert isinstance(pair, Group) and pair.members == ("c_in", "r_pull") and "pair" not in b._groups
    assert len(b.sites_of("unit", "pair")) == 1
    with pytest.raises(TypeError) as e:
        b.alternative(kept, "up", Alt(Part("c_in"), rotation=90))
    assert "board.unit" in str(e.value)
    with pytest.raises(TypeError) as e:
        b.unit("listed", [Part("c_in"), Part("r_pull")])
    assert "one by one" in str(e.value)


def test_a_units_option_lays_its_members_and_leaves_the_rest():
    b, pair = paired()
    up = b.alternative(pair, "up", Alt(Part("c_in"), rotation=90), why="the bypass stands")
    assert isinstance(up, GroupOption) and up.group == "pair" and up.why == "the bypass stands"
    assert [(o.item, o.name) for o in up.options] == [("c_in", "up")]
    assert [s.id for s in b.arrangement_enumeration().specs] == ["default", "pair.up"]
    assert b.arrangement_enumeration().specs[1].choices == {"pair": "up"}
    assert len(b.sites_of("alternative", "pair.up")) == 1


@pytest.mark.parametrize("call, error", [
    (lambda b, g: b.alternative(g, "up", rotation=90), TypeError),                                         # place keywords
    (lambda b, g: b.alternative(g, "up", Alt(Part("u1"), rotation=90)), ValueError),                       # not a member
    (lambda b, g: b.alternative(g, "up", Alt(Part("c_in"), rotation=90), Alt(Part("c_in"), rotation=180)), ValueError),  # twice
    (lambda b, g: b.alternative(g, "up", Part("c_in")), TypeError),                                        # not an Alt
    (lambda b, g: b.alternative(g, "up"), ValueError),                                                     # names no member
    (lambda b, g: b.alternative(g, "Up", Alt(Part("c_in"), rotation=90)), ValueError),                     # not a name
    (lambda b, g: b.alternative(Part("u1"), "up", Alt(Part("u1"), rotation=90)), TypeError),               # an Alt on an item
    (lambda b, g: b.alternative(b.arrangement("m", Alt(Part("u1"), rotation=90)), "x", Alt(Part("u1"), rotation=180)), TypeError),
])
def test_a_bad_unit_option_is_refused_where_it_is_written(call, error):
    b, pair = paired()
    with pytest.raises(error):
        call(b, pair)


def test_a_unit_option_name_is_unique_within_the_unit_and_a_unit_name_is_taken_once():
    b, pair = paired()
    b.alternative(pair, "up", Alt(Part("c_in"), rotation=90))
    with pytest.raises(ValueError):
        b.alternative(pair, "up", Alt(Part("r_pull"), rotation=90))
    with pytest.raises(ValueError):
        b.unit("pair", Part("u1"))
    with pytest.raises(ValueError):
        b.arrangement("pair", Alt(Part("u1"), rotation=90))


def test_a_member_is_in_one_unit_and_has_no_alternative_of_its_own():
    b, pair = paired()
    with pytest.raises(ValueError) as e:
        b.unit("other", Part("c_in"))
    assert "'pair'" in str(e.value) and str(e.value).count(HERE) == 2
    with pytest.raises(ValueError) as e:
        b.alternative(Part("r_pull"), "turned", rotation=180)
    assert "'pair'" in str(e.value) and str(e.value).count(HERE) == 2
    with pytest.raises(ValueError) as e:
        b.arrangement("lifted", Alt(Part("c_in"), rotation=90))
    assert "'pair'" in str(e.value) and str(e.value).count(HERE) == 2
    first = module()
    first.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    with pytest.raises(ValueError) as e:
        first.unit("pair", Part("c_in"))
    assert "'east'" in str(e.value) and str(e.value).count(HERE) == 2
    later = module()
    later.arrangement("lifted", Alt(Part("c_in"), rotation=90))
    with pytest.raises(ValueError) as e:
        later.unit("pair", Part("c_in"))
    assert "'lifted'" in str(e.value) and str(e.value).count(HERE) == 2


def test_a_0_99_15_module_whose_arrangements_share_parts_runs_and_keeps_its_ids():
    """Review focus 1: two board.arrangements over one pair, and one over a part with its own alternative."""
    b = module()
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.arrangement("mirrored", Alt(Part("c_in"), rotation=180), Alt(Part("r_pull"), rotation=180))
    b.arrangement("rotated", Alt(Part("c_in"), rotation=90), Alt(Part("r_pull"), rotation=90))
    b.finish_declarations()
    assert [s.id for s in b.arrangement_enumeration().specs] == ["default", "rotated", "mirrored", "c_in.east"]


def test_a_one_option_unit_combines_with_the_items_it_does_not_move():
    b = module()
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.arrangement("flip", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)), why="the bypass north")
    specs = b.arrangement_enumeration().specs
    assert [s.id for s in specs] == ["default", "flip", "r_pull.turned", "r_pull.turned+flip"]
    assert specs[1].group == "flip" and specs[1].why == "the bypass north"
    assert specs[3].choices == {"r_pull": "turned", "flip": "flip"}
    b.track(Net("VIN"), [PadRef(Part("c_in"), 1), PadRef(Part("u1"), 1)], layer=CopperLayer.F, only=("r_pull.turned+flip",))
    b.finish_declarations()                                     # a combination id the new product makes is known to only=


@pytest.mark.parametrize("only", [("flip+r_pull.turned",), ("r_pull.turned+lifted",)])
def test_only_refuses_an_id_in_the_wrong_order_or_of_units_that_never_combine(only):
    b = module()
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.arrangement("flip", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)))
    b.arrangement("lifted", Alt(Part("r_pull"), at=Beside(Part("u1"), Edge.NORTH)))
    b.track(Net("VIN"), [PadRef(Part("c_in"), 1), PadRef(Part("u1"), 1)], layer=CopperLayer.F, only=only)
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert HERE in str(e.value) and "only=" in str(e.value)


def test_units_take_their_place_in_the_order_the_script_declared_them():
    b = Board(board_geometry(parts(), width=60, height=40), edge_margin=1.0, settings=Settings())
    b.place(Part("u1"), at=Location(20, 15))
    b.place(Part("c_in"), at=Beside(Part("u1"), Edge.WEST))
    pair = b.unit("pair", Part("c_in"))
    b.alternative(pair, "north", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)))
    b.place(Part("r_pull"), at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.alternative(Part("u1"), "turned", rotation=180)          # declared last, but u1's place() came first: the first unit
    assert b._unit_order() == ["u1", "pair", "r_pull"]
    assert [s.id for s in b.arrangement_enumeration().specs] == [
        "default", "r_pull.turned", "pair.north", "pair.north+r_pull.turned", "u1.turned", "u1.turned+r_pull.turned",
        "u1.turned+pair.north", "u1.turned+pair.north+r_pull.turned"]


def test_a_module_of_items_alone_keeps_its_order():
    b = module()
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    assert [s.id for s in b.arrangement_enumeration().specs] == ["default", "r_pull.turned", "c_in.east", "c_in.east+r_pull.turned"]


def test_declared_units_make_their_product():
    b = declared()
    b.finish_declarations()
    assert b._unit_order() == ["r_pull", "cap", "lifted"]
    assert [s.id for s in b.arrangement_enumeration().specs] == [
        "default", "lifted", "cap.north", "cap.north+lifted", "cap.south", "cap.south+lifted", "r_pull.turned",
        "r_pull.turned+cap.north", "r_pull.turned+cap.south"]


def test_an_exclusion_leaves_out_its_combinations_and_keeps_its_why():
    b = declared()
    rule = b.exclude("cap.north", "lifted", why="both stand north of u1")
    b.finish_declarations()
    e = b.arrangement_enumeration()
    assert [(s.id, r) for s, r in e.excluded] == [("cap.north+lifted", rule)] and rule.why == "both stand north of u1"
    assert "cap.north+lifted" not in [s.id for s in e.specs] and e.declared == 8
    assert len(b.sites_of("exclude", "cap.north+lifted")) == 1
    with pytest.raises(TypeError):
        b.exclude("cap.north", 3)


@pytest.mark.parametrize("choices, words", [
    (("cap.north",), "two or more"),
    (("cap.north", "cap.south"), "one at a time"),
    (("cap.north", "nope.x"), "not a choice"),
    (("cap.north+r_pull.turned", "cap.south"), "not a choice"),     # a combination id is not one choice
    (("r_pull.turned", "lifted"), "never combine"),
])
def test_a_bad_exclusion_is_an_error_with_its_line(choices, words):
    """Review focus 4."""
    b = declared()
    b.exclude(*choices)
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert HERE in str(e.value) and words in str(e.value)
    if words == "not a choice":
        assert "cap.north" in str(e.value) and "lifted" in str(e.value)        # the module's choices are listed


def test_a_unit_with_no_option_and_a_unit_named_as_an_item_are_errors_where_the_script_finishes():
    b, _ = paired()
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert HERE in str(e.value) and "'pair'" in str(e.value) and "no option" in str(e.value)
    c = module()
    c.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    g = c.unit("c_in", Part("r_pull"))
    c.alternative(g, "up", Alt(Part("r_pull"), rotation=90))
    with pytest.raises(ValueError) as e:
        c.finish_declarations()
    assert HERE in str(e.value) and "'c_in'" in str(e.value)


def _option_east(b):
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))


def _unit_c_in_east(b):
    g = b.unit("c_in", Part("r_pull"))
    b.alternative(g, "east", Alt(Part("r_pull"), at=Beside(Part("u1"), Edge.NORTH)))


@pytest.mark.parametrize("declare", [
    lambda b: (_option_east(b), _unit_c_in_east(b)),                     # both make the choice id c_in.east
    lambda b: (_unit_c_in_east(b), _option_east(b)),                     # the item's option declared after the unit
    lambda b: (_option_east(b), b.arrangement("c_in", Alt(Part("r_pull"), rotation=90))),
])
def test_a_unit_named_as_an_item_with_options_is_refused_before_its_choices_are_read(declare):
    """A unit named as an item with options would take the item's place among the units and drop its options, and the two can
    make one choice id; the script is refused at the unit's line."""
    b = module()
    declare(b)
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert HERE in str(e.value) and "unit 'c_in'" in str(e.value) and "an item with options" in str(e.value)


def test_a_member_moved_only_by_a_units_option_gets_no_extent_notice():
    b, pair = paired()
    b.alternative(pair, "north", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)))
    extent = [{"item": "c_in", "sides": ["west"], "protrudes_mm": 0.4}, {"item": "r_pull", "sides": ["east"], "protrudes_mm": 0.1}]
    assert [f.facts["item"] for f in run.extent_findings(b, extent, 2.0)] == ["r_pull"]


def _scripted(tmp_path, declaration, draw=""):
    from placemat.project import FabProfile
    from placemat.runner import scripted_board
    from tests.test_arrangement_declarations import _BOARD_SCRIPT
    path = tmp_path / "layout.py"
    path.write_text(_BOARD_SCRIPT.format(draw=draw, declaration=declaration))
    return scripted_board(path, None, Settings(), FabProfile(), True, geometry=board_geometry(parts(), width=60, height=40))


def test_a_board_script_may_still_write_a_kicad_group(tmp_path):
    """Review focus 2."""
    b = _scripted(tmp_path, 'board.group("kept", [Part("c_in")])')          # unchanged by this plan
    assert "kept" in b._groups and b._arr_groups == []


def test_a_board_script_with_a_unit_fails_saying_it_is_a_modules_before_any_other_check(tmp_path):
    from placemat.runner import RunFailure
    with pytest.raises(RunFailure) as e:
        _scripted(tmp_path, 'board.unit("pair", Part("c_in"))')            # no option either: the board's error comes first
    said = str(e.value.details.get("error", "")) + str(e.value)
    assert "module" in said and ":5:" in said and "no option" not in said, said
