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
    """r_pull with its own option; a unit of c_in with two options; a unit of u1 with one."""
    b = module(dataclasses.replace(Settings(), place_arrangements_max=20))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    cap = b.unit("cap", Part("c_in"))
    b.alternative(cap, "north", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)))
    b.alternative(cap, "south", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.SOUTH)))
    lift = b.unit("lift", Part("u1"))
    b.alternative(lift, "up", Alt(Part("u1"), rotation=90))
    return b


def test_board_group_still_writes_a_kicad_group_and_takes_no_option():
    """Review focus 2: board.group is unchanged; the unit is board.unit."""
    b = module()
    kept = b.group("kept", [Part("c_in"), Part("r_pull")], why="moved as one by hand")
    assert isinstance(kept, DeclaredGroup) and "kept" in b._groups and b._arr_groups == []
    pair = b.unit("pair", Part("c_in"), Part("r_pull"))
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
    assert isinstance(up, GroupOption) and up.group == "pair" and up.name == "up" and up.why == "the bypass stands"
    assert [(o.item, o.name) for o in up.options] == [("c_in", "up")]
    assert [s.id for s in b.arrangement_enumeration().specs] == ["default", "pair.up"]
    assert b.arrangement_enumeration().specs[1].choices == {"pair": "up"}
    assert len(b.sites_of("alternative", "pair.up")) == 1


@pytest.mark.parametrize("call, error, words", [
    (lambda b, g: b.alternative(g, "up", rotation=90), TypeError, "not rotation"),                          # place keywords
    (lambda b, g: b.alternative(g, "up", Alt(Part("u1"), rotation=90)), ValueError, "not a member"),        # not a member
    (lambda b, g: b.alternative(g, "up", Alt(Part("c_in"), rotation=90), Alt(Part("c_in"), rotation=180)), ValueError,
     "names c_in twice"),
    (lambda b, g: b.alternative(g, "up", Part("c_in")), TypeError, "takes Alt(member"),                      # not an Alt
    (lambda b, g: b.alternative(g, "up"), ValueError, "names no member"),
    (lambda b, g: b.alternative(g, "Up", Alt(Part("c_in"), rotation=90)), ValueError, "lower-case"),         # not a name
    (lambda b, g: b.alternative(Part("u1"), "up", Alt(Part("u1"), rotation=90)), TypeError, "is for a unit's option"),
    (lambda b, g: b.alternative(Group("ghost", ("u1",)), "x", Alt(Part("u1"), rotation=180)), TypeError, "no unit of that name"),
])
def test_a_bad_unit_option_is_refused_where_it_is_written(call, error, words):
    b, pair = paired()
    with pytest.raises(error) as e:
        call(b, pair)
    assert words in str(e.value), str(e.value)


def test_a_unit_option_name_is_unique_within_the_unit_and_a_unit_name_is_taken_once():
    b, pair = paired()
    b.alternative(pair, "up", Alt(Part("c_in"), rotation=90))
    with pytest.raises(ValueError):
        b.alternative(pair, "up", Alt(Part("r_pull"), rotation=90))
    with pytest.raises(ValueError):
        b.unit("pair", Part("u1"))


def test_a_member_is_in_one_unit_and_has_no_alternative_of_its_own():
    b, pair = paired()
    with pytest.raises(ValueError) as e:
        b.unit("other", Part("c_in"))
    assert "'pair'" in str(e.value) and str(e.value).count(HERE) == 2
    with pytest.raises(ValueError) as e:
        b.alternative(Part("r_pull"), "turned", rotation=180)
    assert "'pair'" in str(e.value) and str(e.value).count(HERE) == 2
    first = module()
    first.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    with pytest.raises(ValueError) as e:
        first.unit("pair", Part("c_in"))
    assert "'east'" in str(e.value) and str(e.value).count(HERE) == 2


def _flip(b):
    flip = b.unit("flip", Part("c_in"))
    b.alternative(flip, "north", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.NORTH)))


def _vin(b, **kw):
    return b.track(Net("VIN"), [PadRef(Part("c_in"), 1), PadRef(Part("u1"), 1)], layer=CopperLayer.F, **kw)


def test_only_matches_every_arrangement_that_holds_its_choices():
    """An only= entry names a choice or a combination; the copper exists in every arrangement that holds all of an entry's
    choices, and `default` is the module's own layout alone."""
    b = module()
    b.alternative(Part("r_pull"), "turned", rotation=180)
    _flip(b)
    one, both, own = _vin(b, only=("flip.north",)), _vin(b, only=("r_pull.turned+flip.north",)), _vin(b, only=("default",))
    b.finish_declarations()
    specs = b.arrangement_enumeration().specs
    assert [s.id for s in specs] == ["default", "flip.north", "r_pull.turned", "r_pull.turned+flip.north"]
    assert [s.id for s in specs if one.applies_in(s.held)] == ["flip.north", "r_pull.turned+flip.north"]
    assert [s.id for s in specs if both.applies_in(s.held)] == ["r_pull.turned+flip.north"]
    assert [s.id for s in specs if own.applies_in(s.held)] == ["default"]


def test_copper_on_a_unit_option_is_laid_in_every_combination_that_holds_it():
    b = module()
    b.alternative(Part("r_pull"), "turned", rotation=180)
    _flip(b)
    _vin(b, only=("flip.north",))
    _vin(b)
    prepared = run.begin(b)
    kept = {}
    for spec in prepared.specs:
        b._restore(prepared.saved)
        b.lay_arrangement(spec)
        kept[spec.id] = len(b._copper)
    assert kept == {"default": 1, "flip.north": 2, "r_pull.turned": 1, "r_pull.turned+flip.north": 2}


@pytest.mark.parametrize("only", [("flip.north+r_pull.turned",), ("flip",), ("r_pull",)])
def test_only_refuses_an_id_in_the_wrong_order_or_a_unit_name(only):
    b = module()
    b.alternative(Part("r_pull"), "turned", rotation=180)
    _flip(b)
    _vin(b, only=only)
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    said = str(e.value)
    assert HERE in said and "only=" in said and "r_pull.turned, flip.north" in said and "groups" not in said, said


def test_only_naming_an_excluded_combination_is_an_error():
    b = declared()
    b.exclude("r_pull.turned", "cap.north", why="both stand north")
    _vin(b, only=("r_pull.turned+cap.north",))
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert HERE in str(e.value) and "board.exclude" in str(e.value) and "'r_pull.turned+cap.north'" in str(e.value)
    held = declared()
    held.exclude("r_pull.turned", "cap.north")
    _vin(held, only=("r_pull.turned+cap.north+lift.up", "cap.north"))
    with pytest.raises(ValueError):
        held.finish_declarations()                              # the first entry is held only by excluded combinations
    fine = declared()
    fine.exclude("r_pull.turned", "cap.north")
    _vin(fine, only=("cap.north", "r_pull.turned"))
    fine.finish_declarations()


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
    assert b._unit_order() == ["r_pull", "cap", "lift"]
    assert [s.id for s in b.arrangement_enumeration().specs] == [
        "default", "lift.up", "cap.north", "cap.north+lift.up", "cap.south", "cap.south+lift.up", "r_pull.turned",
        "r_pull.turned+lift.up", "r_pull.turned+cap.north", "r_pull.turned+cap.north+lift.up", "r_pull.turned+cap.south",
        "r_pull.turned+cap.south+lift.up"]


def test_an_exclusion_leaves_out_its_combinations_and_keeps_its_why():
    b = declared()
    rule = b.exclude("cap.north", "lift.up", why="both stand north of u1")
    b.finish_declarations()
    e = b.arrangement_enumeration()
    assert [(s.id, r) for s, r in e.excluded] == [("cap.north+lift.up", rule), ("r_pull.turned+cap.north+lift.up", rule)]
    assert rule.why == "both stand north of u1"
    assert "cap.north+lift.up" not in [s.id for s in e.specs] and e.declared == 10
    assert len(b.sites_of("exclude", "cap.north+lift.up")) == 1
    with pytest.raises(TypeError):
        b.exclude("cap.north", 3)


@pytest.mark.parametrize("choices, words", [
    (("cap.north",), "two or more"),
    (("cap.north", "cap.south"), "one at a time"),
    (("cap.north", "nope.x"), "not a choice"),
    (("cap.north+r_pull.turned", "cap.south"), "not a choice"),     # a combination id is not one choice
    (("cap.north", "cap.north"), "cap.north twice"),
])
def test_a_bad_exclusion_is_an_error_with_its_line(choices, words):
    """Review focus 4."""
    b = declared()
    b.exclude(*choices)
    with pytest.raises(ValueError) as e:
        b.finish_declarations()
    assert HERE in str(e.value) and words in str(e.value)
    if words == "not a choice":
        assert "cap.north" in str(e.value) and "lift.up" in str(e.value)       # the module's choices are listed


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


def test_a_board_script_with_an_exclusion_alone_fails_saying_an_exclusion_is_a_modules(tmp_path):
    from placemat.runner import RunFailure
    with pytest.raises(RunFailure) as e:
        _scripted(tmp_path, 'board.exclude("c_in.east", "u1.turned")')
    said = str(e.value.details.get("error", "")) + str(e.value)
    assert ":5:" in said and "board.exclude" in said and "module" in said, said
    assert "declares an arrangement" not in said and "exclusion" in said, said
