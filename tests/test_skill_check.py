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
