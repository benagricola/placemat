"""board.push(): an item held back from a source by a physical falloff
model, not a hand-picked point. Pure declaration and ordering here; the
hard limit, the soft price and the step note are later tasks."""
import pytest

from placemat.layout import Board
from placemat.values import Location, PadRef, Part, Priority
from tests.fixtures import board_geometry, footprint


def _board():
    fps = [footprint("M1", 10, 10, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 30, 30, w=2, h=2, inst="u2", nets=("SIG", "GND"))]
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)


def test_push_needs_a_place_declaration_first():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    with pytest.raises(ValueError, match="place"):
        b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)


def test_push_validates_its_numbers():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"))
    with pytest.raises(ValueError):
        b.push(Part("u2"), from_=Part("m1"), falloff=0, reference=(13.5, 3.2), limit=0.3)
    with pytest.raises(ValueError):
        b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(0, 3.2), limit=0.3)
    with pytest.raises(ValueError):
        b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0)
    with pytest.raises(ValueError):
        b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 0), limit=0.3)


def test_push_from_an_unknown_keepout_name_is_refused():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"))
    with pytest.raises(ValueError, match="keepout"):
        b.push(Part("u2"), from_="nope", falloff=3, reference=(13.5, 3.2), limit=0.3)


def test_a_push_attaches_to_the_items_own_intent():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    intent = b.place(Part("u2"))
    p = b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3, why="field at the sensor")
    assert intent.pushes == (p,)
    assert p.falloff == 3 and p.r_ref == 13.5 and p.v_ref == 3.2 and p.limit == 0.3
    assert p.why == "field at the sensor"
    assert p.target_pad_key is None


def test_a_push_on_a_padref_records_which_pad():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"))
    p = b.push(PadRef(Part("u2"), "SIG"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    assert p.target_pad_key == ("U2", "1")


def test_a_pushed_item_waits_for_its_source_when_both_are_searched():
    b = _board()
    b.place(Part("m1"))
    b.place(Part("u2"))
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    m1_intent = next(i for i in b._intents if i.key == "m1")
    assert m1_intent.needs == frozenset()
    u2_intent = next(i for i in b._intents if i.key == "u2")
    assert u2_intent.needs == frozenset({"M1"})
