"""board.push(): an item held back from a source by a physical falloff
model, not a hand-picked point. Pure declaration and ordering here; the
hard limit, the soft price and the step note are later tasks."""
import pytest

from placemat.layout import Board
from placemat.values import Face, Location, PadRef, Part, Priority
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


def test_a_pushed_item_lands_at_or_under_the_limit_and_farther_than_unpushed():
    fps = [footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND")),
           footprint("J1", 55, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))]
    without = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    without.place(Part("m1"), at=Location(10, 30))
    without.place(Part("j1"), at=Location(55, 30))
    without.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"))
    without.place(Part("u2"), radius=25.0, step=1.0)
    plan_without = without.resolve()
    d_without = plan_without.box("u2").center.distance(Location(10, 30))

    pushed = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    pushed.place(Part("m1"), at=Location(10, 30))
    pushed.place(Part("j1"), at=Location(55, 30))
    pushed.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"))
    pushed.place(Part("u2"), radius=25.0, step=1.0)
    pushed.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(2.0, 3.2), limit=0.3, why="field at the sensor")
    plan_pushed = pushed.resolve()
    d_pushed = plan_pushed.box("u2").center.distance(Location(10, 30))

    value = 3.2 * (2.0 / d_pushed) ** 3
    assert value <= 0.3 + 1e-6
    assert d_pushed > d_without


def test_two_pushes_add_and_push_the_item_farther_than_one():
    """j1 sits right beside m1, so the link pulling u2 toward j1 and the
    push holding it back from m1 oppose each other at nearly the same
    point: a genuine interior tug of war, not a race to the board edge.
    With weight=1 mm/mm and falloff=1, the equilibrium is where
    d(push)/dr = weight, at r = sqrt(n * score_push * v_ref * r_ref /
    (limit * weight)) - about 8.4 mm for one push, 11.9 mm for two."""
    def _run(n_pushes):
        fps = [footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND")),
               footprint("U2", 30, 30, w=2, h=2, inst="u2", nets=("SIG", "GND")),
               footprint("J1", 16, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))]
        b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
        b.place(Part("m1"), at=Location(10, 30))
        b.place(Part("j1"), at=Location(16, 30))
        b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"), weight=1)
        b.place(Part("u2"), radius=20.0, step=0.25)
        for _ in range(n_pushes):
            b.push(Part("u2"), from_=Part("m1"), falloff=1, reference=(2.0, 3.2), limit=0.9,
                   why="field at the sensor")
        plan = b.resolve()
        return plan.box("u2").center.distance(Location(10, 30))

    assert _run(2) > _run(1)


def test_native_scoring_is_bypassed_for_a_pushed_item():
    from placemat.layout import Push, Scorer
    from placemat.occupancy import Occupancy
    fps = [footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND"))]
    g = board_geometry(fps, width=60, height=60)
    occ = Occupancy(g, edge_margin=1.0)
    u2 = g.footprint("U2")
    push = Push(Location(10, 30), 3.0, 2.0, 3.2, 0.3)
    scorer = Scorer(occ.settings, u2, occ, [], False, pushes=[(Location(10, 30), push)])
    assert scorer.native((0.0,), Face.FRONT) is None


def test_a_pushed_item_with_nowhere_legal_is_unplaced_not_a_crash():
    """Every candidate anywhere on this tiny board is inside the hard-limit
    disc (a huge v_ref against a tiny limit): the wide scan finds nothing,
    and that is an ordinary unplaced finding, not an exception."""
    fps = [footprint("M1", 5, 5, w=2, h=2, inst="m1", nets=("A", "GND")),
           footprint("U2", 15, 15, w=2, h=2, inst="u2", nets=("SIG", "GND"))]
    b = Board(board_geometry(fps, width=20, height=20), edge_margin=0.5)
    b.place(Part("m1"), at=Location(5, 5))
    b.place(Part("u2"))
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(1.0, 1000.0), limit=0.01)
    plan = b.resolve()
    assert plan.step("u2").placement is None
    assert any("u2" in f for f in plan.findings)


def test_the_step_note_gives_the_value_and_the_distance():
    fps = [footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND")),
           footprint("J1", 55, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("m1"), at=Location(10, 30))
    b.place(Part("j1"), at=Location(55, 30))
    b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"))
    b.place(Part("u2"), radius=25.0, step=1.0)
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(2.0, 3.2), limit=0.3, why="field at the sensor")
    plan = b.resolve()
    note = plan.step("u2").note
    assert "push from m1:" in note and "limit 0.3" in note and "mm" in note
    assert len(plan.pushes) == 1
    p = plan.pushes[0]
    assert p.achieved_value is not None and p.achieved_value <= 0.3 + 1e-6
    assert p.achieved_mm is not None and p.achieved_mm > 0


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
