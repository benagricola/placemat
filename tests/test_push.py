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
    return Board(board_geometry(fps, width=60, height=60), edge_margin=1.0, keep_going=True)


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


def test_a_firm_spot_inside_the_hard_limit_is_refused():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    # the disc's radius: 13.5 * (3.2 / 0.3) ** (1/3) ~= 29.7 mm - anywhere on this 60x60 board
    # is inside it, so a firm spot a few mm from m1 is refused
    b.place(Part("u2"), at=Location(14, 10))
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    plan = b.resolve()
    findings = [f for f in plan.findings if "u2" in f]
    assert any("push from m1" in f and "limit 0.3" in f for f in findings), findings


def test_the_disc_radius_follows_the_formula():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"), at=Location(15, 10))     # 5 mm from m1, clear of its courtyard, inside any sane disc
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    plan = b.resolve()
    radius = 13.5 * (3.2 / 0.3) ** (1.0 / 3.0)
    assert radius == pytest.approx(29.71, rel=0.01)
    findings = [f for f in plan.findings if "u2" in f]
    assert any(("%.3g" % radius) in f for f in findings), findings


def test_falloff_changes_the_disc_radius():
    b3 = _board()
    b3.place(Part("m1"), at=Location(10, 10))
    b3.place(Part("u2"), at=Location(15, 10))
    b3.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    plan3 = b3.resolve()
    b1 = _board()
    b1.place(Part("m1"), at=Location(10, 10))
    b1.place(Part("u2"), at=Location(15, 10))
    b1.push(Part("u2"), from_=Part("m1"), falloff=1, reference=(13.5, 3.2), limit=0.3)
    plan1 = b1.resolve()
    r1 = next(f for f in plan1.findings if "u2" in f)
    r3 = next(f for f in plan3.findings if "u2" in f)
    assert r1 != r3    # different formula, different radius, different sentence


def test_every_other_part_is_still_let_in():
    """The disc is reserved against the pushed item alone: a different part
    may stand inside it, right beside the source."""
    fps = [footprint("M1", 10, 10, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 30, 30, w=2, h=2, inst="u2", nets=("SIG", "GND")),
           footprint("R1", 18, 10, w=1, h=1, inst="r1", nets=("A", "B"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"))
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)
    b.place(Part("r1"), at=Location(18, 10))     # clear of m1's own courtyard, well inside u2's disc
    plan = b.resolve()
    assert not any("r1" in f for f in plan.findings), plan.findings
