import importlib.util
import pathlib

BENCH = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "skill_check.py"


def load():
    spec = importlib.util.spec_from_file_location("skill_check", BENCH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ROLES = {"bypass": ["c_hf1"], "pullup": ["r_pull"], "polarised": ["bulk_a"], "protruding": ["bulk_b"]}
GOOD = '''
board.place(Part("c_hf1"), at=Beside(Part("u1"), Edge.NORTH))
board.alternative(Part("c_hf1"), "south", at=Beside(Part("u1"), Edge.SOUTH))
board.place(Part("r_pull"), at=Beside(Part("u1"), Edge.EAST))
board.alternative(Part("r_pull"), "turned", rotation=180)
board.place(Part("bulk_b"), at=Beside(Part("u1"), Edge.EAST))
board.alternative(Part("bulk_b"), "tucked", rotation=90)
board.place(Part("bulk_a"), at=Beside(Part("u1"), Edge.WEST))
'''


def test_a_script_that_follows_the_skill_passes():
    assert load().check(GOOD, ROLES) == []


def test_each_departure_is_named():
    m = load()
    assert any("bypass" in f for f in m.check(GOOD.replace('board.alternative(Part("c_hf1"), "south", at=Beside(Part("u1"), Edge.SOUTH))\n', ""), ROLES))
    assert any("polarised" in f for f in m.check(GOOD + 'board.alternative(Part("bulk_a"), "flipped", rotation=180)\n', ROLES))
    assert any("name" in f for f in m.check(GOOD.replace('"south"', '"alt1"'), ROLES))
    assert any("extent" in f or "protruding" in f for f in m.check(GOOD.replace('board.alternative(Part("bulk_b"), "tucked", rotation=90)\n', ""), ROLES))
    ok = GOOD.replace('board.alternative(Part("bulk_b"), "tucked", rotation=90)\n', "# extent: bulk_b is a fact of its datasheet figure\n")
    assert m.check(ok, ROLES) == []


def test_a_bypass_with_no_room_to_turn_passes_with_a_stated_reason():
    m = load()
    no_turn = GOOD.replace('board.alternative(Part("c_hf1"), "south", at=Beside(Part("u1"), Edge.SOUTH))\n', "")
    assert any("bypass" in f for f in m.check(no_turn, ROLES))
    assert m.check(no_turn + "# fixed: c_hf1 no turn fits between u1's pin and r_pull\n", ROLES) == []
    assert any("bypass" in f for f in m.check(no_turn + "# extent: c_hf1 a reason of the wrong kind\n", ROLES))


UNITS = GOOD + '''
pair = board.unit("pair", Part("c1"), Part("r1"))
board.alternative(pair, "flat", Alt(Part("c1"), rotation=0), Alt(Part("r1"), rotation=90))
board.alternative(pair, "upright", Alt(Part("c1"), rotation=90))
caps = board.unit("caps", Part("c2"), Part("c3"))
board.alternative(caps, "north", Alt(Part("c2"), rotation=90), Alt(Part("c3"), rotation=90))
board.alternative(caps, "south", Alt(Part("c3"), rotation=270))
'''


def test_a_unit_option_counts_for_each_member_it_moves():
    m = load()
    assert m.check(UNITS, ROLES) == []
    moved_by_unit = dict(ROLES, bypass=["c_hf1", "c3"])          # c3 moves only with its unit
    assert m.check(UNITS, moved_by_unit) == []
    assert any("c1" in f and "polarised" in f for f in m.check(UNITS, dict(ROLES, polarised=["c1"])))


def test_a_unit_over_the_cap_is_named_and_two_units_are_not_added_together():
    m = load()
    more = UNITS + "".join('board.alternative(pair, "o%d", Alt(Part("r1"), rotation=%d))\n' % (i, 90 * i) for i in range(1, 4))
    found = m.check(more, ROLES)
    assert any(f.startswith("pair has 6 options") for f in found) and any(f.startswith("r1 has 5 options") for f in found)
    assert not any(f.startswith("caps") or f.startswith(" ") for f in found)


def test_a_unit_named_alt_is_flagged():
    m = load()
    assert any("'alt1' names nothing" in f for f in m.check(UNITS.replace('board.unit("caps"', 'board.unit("alt1"'), ROLES))
