import pytest

from placemat import arrangements as A


def opt(item, name, **kw):
    return A.Option(item, name, tuple(kw.items()))


def test_a_name_is_lower_case_words_digits_and_underscores():
    A.check_name("option", "east_2")
    for bad in ("East", "a-b", "a.b", "a+b", "", "default"):
        with pytest.raises(ValueError):
            A.check_name("option", bad)


def test_an_option_takes_the_place_keywords_that_say_where_and_why():
    A.check_keywords("c_in", {"at": 1, "rotation": 90, "rotations": (0, 90), "face": 1, "radius": 2, "step": 0.1, "why": "w"})
    with pytest.raises(TypeError) as e:
        A.check_keywords("c_in", {"required": True})
    assert "required" in str(e.value) and "rotation" in str(e.value)


def test_the_arrangements_are_the_default_then_the_product_with_a_board_arrangement_as_one_more_unit():
    """A 0.99.15 board.arrangement keeps its id; it moves c_in and r_pull, which have options of their own, so it combines with neither."""
    options = {"c_in": [opt("c_in", "east")], "r_pull": [opt("r_pull", "turned"), opt("r_pull", "back")]}
    group = A.Group("mirrored", (opt("c_in", "mirrored"), opt("r_pull", "mirrored")))
    e = A.enumerate_specs(["c_in", "r_pull"], options, [group], 4, 20)
    assert [s.id for s in e.specs] == ["default", "mirrored", "r_pull.turned", "r_pull.back", "c_in.east",
                                       "c_in.east+r_pull.turned", "c_in.east+r_pull.back"]
    assert e.over is None and e.declared == 7
    both = e.specs[5]
    assert both.choices == {"c_in": "east", "r_pull": "turned"} and [k for k, _ in both.overrides] == ["c_in", "r_pull"]
    assert e.specs[1].choices == {"mirrored": "mirrored"} and e.specs[1].group == "mirrored" and e.specs[0].choices == {}


def test_exactly_the_limit_is_accepted_and_one_over_is_not():
    options = {"a": [opt("a", "x")], "b": [opt("b", "x")], "c": [opt("c", "x")]}      # 2 * 2 * 2 = 8
    assert A.enumerate_specs(["a", "b", "c"], options, [], 4, 8).over is None
    over = A.enumerate_specs(["a", "b", "c"], options, [A.Group("g", (opt("a", "g"),))], 4, 8)
    assert [s.id for s in over.specs] == ["default"]
    assert over.over == {"variant": "arrangements", "arrangements": 12, "max_arrangements": 8,       # g moves a: 8 + 4 with b and c
                         "options": {"a": 2, "b": 2, "c": 2, "g": 2}, "max_options": 4, "excluded": 0}


def test_an_item_over_the_option_limit_is_the_options_variant():
    options = {"a": [opt("a", n) for n in "wxyz"]}      # 5 with its place()
    e = A.enumerate_specs(["a"], options, [], 4, 100)
    assert e.over["variant"] == "options" and e.over["options"] == {"a": 5} and len(e.specs) == 1


def test_an_id_is_known_as_written():
    options = {"c_in": [opt("c_in", "east")], "r.pull": [opt("r.pull", "turned")]}
    group = A.Group("mirrored", ())
    args = (["c_in", "r.pull"], options, [group])
    for ok in ("default", "mirrored", "c_in.east", "r.pull.turned", "c_in.east+r.pull.turned"):
        assert A.known_id(ok, *args), ok
    for bad in ("east", "c_in.west", "r.pull.turned+c_in.east", "c_in.east+c_in.east", "nope"):
        assert not A.known_id(bad, *args), bad


def test_the_default_arrangement_has_no_overrides():
    assert A.DEFAULT_SPEC.id == "default" and A.DEFAULT_SPEC.choices == {} and A.DEFAULT_SPEC.overrides == ()


def test_all_ids_are_the_enumerated_ids_up_to_the_cap():
    options = {"c_in": [opt("c_in", "east")], "r_pull": [opt("r_pull", "turned"), opt("r_pull", "back")]}
    group = A.Group("mirrored", ())
    args = (["c_in", "r_pull"], options, [group])
    assert A.all_ids(*args) == [s.id for s in A.enumerate_specs(*args, 4, 20).specs]
    assert A.all_ids(*args, cap=3) == ["default", "mirrored", "r_pull.turned"]


from placemat import Alt
from placemat.values import Beside, Edge, Location, Near, Part, Turned
from tests.arrangement_support import module


def test_an_option_inherits_the_places_keywords_and_replaces_the_ones_it_gives():
    b = module()
    opt = b.alternative(Part("r_pull"), "turned", rotation=180)
    i = b._intent_option(opt)
    assert i.rotation == 180.0 and i.beside is not None and i.why == "pull-up at OUT" and i.key == "r_pull"
    east = b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST), why="bypass on the output side")
    j = b._intent_option(east)
    assert j.beside.side == Edge.EAST and j.rotation == 0.0 and east.why == "bypass on the output side"


def test_an_options_turn_replaces_the_places_way_of_turning_and_keeps_the_rest():
    """Review focus 5: rotation= over rotations= or a Turned, rotations= over rotation=, and at= over a Near keeps the radius."""
    b = module()
    b.place(Part("r_free"), at=Near(Location(40, 10), radius=4.0), rotations=(0, 90))
    turned = b._intent_option(b.alternative(Part("r_free"), "turned", rotation=180))
    assert turned.rotations == () and turned.rotation == 180.0 and turned.rotation_given and turned.near is not None
    assert turned.radius == 4.0
    spread = b._intent_option(b.alternative(Part("r_free"), "spread", rotations=(0, 180)))
    assert tuple(float(r) for r in spread.rotations) == (0.0, 180.0) and not spread.rotation_given
    beside = b._intent_option(b.alternative(Part("r_free"), "beside", at=Beside(Part("u1"), Edge.NORTH)))
    assert beside.beside is not None and beside.near is None and beside.radius == b.settings.place_radius
    assert tuple(beside.rotations) == (0.0, 90.0)           # the item's own rotations stay when the option gives no turn
    b2 = module()
    b2.place(Part("r_free"), at=Beside(Part("u1"), Edge.NORTH), rotation=Turned(Part("u1"), 90))
    flat = b2._intent_option(b2.alternative(Part("r_free"), "flat", rotation=0))
    assert flat.turned is None and flat.rotation == 0.0


@pytest.mark.parametrize("call, error", [
    (lambda b: b.alternative(Part("r_free"), "x", rotation=90), ValueError),            # no place() of its own
    (lambda b: b.alternative(Part("r_pull"), "x", required=True), TypeError),           # not a keyword an option may change
    (lambda b: b.alternative(Part("r_pull"), "East", rotation=90), ValueError),         # not a lower-case word
    (lambda b: b.alternative(Part("r_pull"), "default", rotation=90), ValueError),      # reserved
    (lambda b: b.alternative(Part("r_pull"), "x", at=Location(3, 4)), TypeError),        # a coordinate
    (lambda b: b.alternative(Part("r_pull"), "x", bogus=1), TypeError),
])
def test_a_bad_alternative_is_refused_where_it_is_written(call, error):
    b = module()
    with pytest.raises(error):
        call(b)


def test_a_duplicate_option_name_and_a_row_members_alternative_are_refused():
    b = module()
    b.alternative(Part("r_pull"), "turned", rotation=180)
    with pytest.raises(ValueError):
        b.alternative(Part("r_pull"), "turned", rotation=90)
    b.row([Part("r_free")], Edge.NORTH)
    with pytest.raises(ValueError) as e:
        b.alternative(Part("r_free"), "x", rotation=90)
    assert "board.unit" in str(e.value)


def test_an_alternative_is_not_a_second_place_and_leaves_the_declarations_alone():
    b = module()
    before = [i.key for i in b._intents]
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    assert [i.key for i in b._intents] == before
    assert len(b.sites_of("place", "c_in")) == 1 and len(b.sites_of("alternative", "c_in.east")) == 1


def test_a_group_names_the_members_it_moves_and_the_ids_are_formed_as_specified():
    b = module()
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)
    b.arrangement("mirrored", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.EAST), rotation=180),
                  Alt(Part("r_pull"), at=Beside(Part("u1"), Edge.WEST)), why="mirrored")
    ids = [s.id for s in b.arrangement_enumeration().specs]
    assert ids == ["default", "mirrored", "r_pull.turned", "c_in.east", "c_in.east+r_pull.turned"]
    with pytest.raises(ValueError):
        b.arrangement("mirrored", Alt(Part("c_in"), rotation=90))                     # a second group of that name
    with pytest.raises(TypeError):
        b.arrangement("x", Part("c_in"))                                              # not an Alt
    with pytest.raises(ValueError):
        b.arrangement("y", Alt(Part("c_in"), rotation=90), Alt(Part("c_in"), rotation=180))   # a member twice


def test_the_limits_leave_the_default_alone_and_the_switch_does_too():
    import dataclasses
    from placemat.settings import Settings
    b = module(dataclasses.replace(Settings(), place_arrangements_max=2))
    b.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    b.alternative(Part("r_pull"), "turned", rotation=180)            # 2 * 2 = 4 > 2
    assert [s.id for s in b.arrangement_enumeration().specs] == ["default"]
    assert b.arrangement_limit()["variant"] == "arrangements"
    off = module(dataclasses.replace(Settings(), place_arrangements=False))
    off.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))
    assert [s.id for s in off.arrangement_enumeration().specs] == ["default"] and off.arrangement_limit() is None


def test_a_group_may_name_a_row_member_and_re_placing_it_keeps_the_rows_standoff():
    from placemat.layout import Board
    from placemat.settings import Settings
    from tests.arrangement_support import parts
    from tests.fixtures import board_geometry, footprint
    big = footprint("R3", 30, 30, w=3, h=4.0, nets=("OUT", "GND"), inst="r_big")
    b = Board(board_geometry(parts() + [big], width=60, height=40), edge_margin=1.0, settings=Settings())
    b.row([Part("r_free"), Part("r_big")], Edge.NORTH)
    original = b._intents[0]
    assert original.key == "r_free" and original.clearance != b.keep_in          # the row gave the shallower item its own standoff
    group = b.arrangement("moved", Alt(Part("r_free"), rotation=90), why="turned")
    i = b._intent_option(group.options[0])
    assert i.rotation == 90.0 and i.clearance == original.clearance and i.row_of == original.row_of and i.key == "r_free"
    with pytest.raises(ValueError):
        b.alternative(Part("r_big"), "x", rotation=90)
    assert [s.id for s in b.arrangement_enumeration().specs] == ["default", "moved"]


from pathlib import Path

_SKILLS = Path(__file__).resolve().parent.parent / "skills/placemat"
SKILL = (_SKILLS / "SKILL.md").read_text()
API = (_SKILLS / "references/api.md").read_text()


def test_the_skill_and_api_document_the_forms_and_the_report():
    for word in ("board.alternative", "board.arrangement", "only=", "arrangement.refused", "arrangement.limit",
                 "arrangement.extent_fixed", "place.arrangement_options_max", "place.arrangements_max"):
        assert word in API, word
    assert "add it as an alternative first" in SKILL and "extent" in SKILL and "arrangement.refused" in SKILL
    assert all(ord(c) < 128 for c in SKILL + API), "ASCII only"


def test_the_skill_names_the_board_side():
    assert "arrangements=" in SKILL and "does not edit a module's default" in SKILL
    assert "arrangements=" in API and "arrangement.missing" in API and "arrangement.stale" in API
    for reason in ("version", "base", "offset", "member", "net", "text"):
        assert "| `%s` |" % reason in API, reason
    assert all(ord(c) < 128 for c in SKILL + API), "ASCII only"


def test_the_migration_entry_names_what_a_board_must_know():
    doc = (_SKILLS / "references/migration.md").read_text()
    text = doc.split("## To 0.99.15", 1)[1].split("\n## To ", 1)[0]  # the release that brought arrangements
    for word in ("arrangements=", "arrangement", "re-run", "default", "place.arrangements"):
        assert word in text, word
    section = API.split("**Arrangements.**", 1)[1].split("**How a searched item finds its place.**")[0]
    assert "plan.json" in section and "place.arrangement_margin" in section


_BOARD_SCRIPT = """from placemat import board, Alt, Beside, Edge, Location, Part
board.rect(60, 40{draw})
board.place(Part("u1"), at=Location(20, 15))
board.place(Part("c_in"), at=Beside(Part("u1"), Edge.WEST))
{declaration}
"""


@pytest.mark.parametrize("declaration", ['board.alternative(Part("c_in"), "east", at=Beside(Part("u1"), Edge.EAST))',
                                         'board.arrangement("east", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.EAST)))',
                                         'pair = board.unit("pair", Part("c_in")); '
                                         'board.alternative(pair, "east", Alt(Part("c_in"), at=Beside(Part("u1"), Edge.EAST)))'])
def test_a_board_script_that_declares_alternatives_fails_saying_they_are_a_modules(tmp_path, declaration):
    from placemat.project import FabProfile
    from placemat.runner import RunFailure, scripted_board
    from placemat.settings import Settings
    from tests.arrangement_support import parts
    from tests.fixtures import board_geometry
    path = tmp_path / "layout.py"
    path.write_text(_BOARD_SCRIPT.format(draw="", declaration=declaration))
    with pytest.raises(RunFailure) as e:
        scripted_board(path, None, Settings(), FabProfile(), True, geometry=board_geometry(parts(), width=60, height=40))
    said = str(e.value.details.get("error", "")) + str(e.value)
    assert "module" in said and ":5:" in said, said
    path.write_text(_BOARD_SCRIPT.format(draw=", draw=False", declaration=declaration))      # a module: its frame is not drawn
    b = scripted_board(path, None, Settings(), FabProfile(), True, geometry=board_geometry(parts(), width=60, height=40))
    assert len(b.arrangement_specs()) == 2


def test_the_skill_and_api_document_units_exclusions_and_dead_options():
    section = API.split("**Arrangements.**", 1)[1].split("**How a searched item finds its place.**")[0]
    for word in ("board.unit(", "board.alternative(unit", "board.exclude(", "arrangement.option_dead", '"excluded"',
                 "unit.option", "never combine", "(default 16)"):
        assert word in section, word
    for word in ("arrangement.option_dead", "board.exclude", "board.unit", "needs no action"):
        assert word in SKILL, word
    unreleased = (_SKILLS / "references/migration.md").read_text().split("## Unreleased", 1)[1].split("\n## To ", 1)[0]
    for word in ("board.unit", "board.exclude", "arrangement.option_dead", "run again", "keeps its id", "place.arrangements_max", "16"):
        assert word in unreleased, word
    assert unreleased.count("### Changed") == 1 and unreleased.count("### New") == 1
    assert all(ord(c) < 128 for c in SKILL + API + unreleased), "ASCII only"
