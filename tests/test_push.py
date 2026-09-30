"""board.push(): an item held back from a source by a physical falloff
model, not a hand-picked point. Pure declaration and ordering here; the
hard limit, the soft price and the step note are later tasks."""
import pytest

from placemat.cutouts import Circle
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


def test_a_firm_pushed_item_waits_for_a_firm_keepout_source_whatever_order_they_are_declared():
    """A keepout's own needs, not text order, decide readiness in the firm
    tier: declared after u2, "hot" still has no needs of its own and goes
    first, so u2's push resolves without a KeyError from plan.keepouts."""
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"), at=Location(40, 40))
    b.keepout(Circle(4.0), "hot", at=Location(10, 10), why="near m1")
    b.push(Part("u2"), from_="hot", falloff=3, reference=(13.5, 3.2), limit=0.3)
    plan = b.resolve()
    assert plan.step("u2").placement is not None


def test_a_firm_pushed_item_cannot_reference_a_searched_keepout_source():
    """A keepout searched round a hint settles in a later tier than any
    firm item: a firm pushed item can never legally wait for one, and that
    is the existing, clear "not placed by then" error, not a KeyError."""
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"), at=Location(40, 40))
    from placemat.values import Near
    b.keepout(Circle(4.0), "hot", at=Near(Location(10, 10)), why="near m1")
    b.push(Part("u2"), from_="hot", falloff=3, reference=(13.5, 3.2), limit=0.3)
    with pytest.raises(ValueError, match="not placed by then"):
        b.resolve()


def test_a_searched_pushed_item_waits_for_its_keepout_source():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.keepout(Circle(4.0), "hot", at=Location(10, 10), why="near m1")
    b.place(Part("u2"), radius=20.0, step=1.0)
    b.push(Part("u2"), from_="hot", falloff=3, reference=(13.5, 3.2), limit=0.3)
    plan = b.resolve()
    assert plan.step("u2").placement is not None


def test_push_on_a_block_member_is_refused_not_silently_ignored():
    """_settle_block returns before _reserve_pushes ever runs: a push
    attached to a block's anchor or a satellite would otherwise do
    nothing, with no finding and no note - refuse it at declaration."""
    fps = [footprint("M1", 50, 50, w=4, h=4, inst="m1", nets=("PWR", "GND")),
           footprint("U1", 30, 30, w=6, h=3, inst="ldo", nets=("VIN", "VOUT")),
           footprint("C1", 10, 10, inst="cin", nets=("VIN", "GND"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("m1"), at=Location(50, 50))
    blk = b.block(Part("ldo"), satellites=[(Part("cin"), "VIN")])
    b.place(blk)
    with pytest.raises(TypeError, match="block"):
        b.push(Part("ldo"), from_=Part("m1"), falloff=3, reference=(13.5, 3.2), limit=0.3)


def test_a_pushed_item_on_a_fit_board_does_not_crash():
    """A module fragment sizes its own frame to its content (fit=True):
    board.centre is refused until something is placed, and a pushed item
    with nothing else pulling it must not reach for it."""
    fps = [footprint("M1", 20, 20, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 30, 30, w=2, h=2, inst="u2", nets=("SIG", "PWR"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=0.5)
    b.size(fit=True, draw=False)
    b.place(Part("m1"), at=Location(0, 0))
    b.place(Part("u2"))
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(2.0, 3.2), limit=0.3)
    plan = b.resolve()
    assert plan.step("u2").placement is not None


def test_a_linked_pushed_item_still_gets_the_wide_scan():
    """A push with a link too (the common case: a real sensor has nets) must
    not lose the wide scan just because a link also seeds a hint: with no
    radius= given, the default (3 mm) can never clear a disc this size from
    a hint planted inside it, and the item would fall back to a pocket with
    no push report."""
    fps = [footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND")),
           footprint("J1", 16, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("m1"), at=Location(10, 30))
    b.place(Part("j1"), at=Location(16, 30))
    b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"))
    b.place(Part("u2"))            # no radius=: the default (3 mm) alone cannot clear the disc
    b.push(Part("u2"), from_=Part("m1"), falloff=3, reference=(2.0, 3.2), limit=0.02,
           why="field at the sensor")
    plan = b.resolve()
    assert plan.step("u2").placement is not None
    note = plan.step("u2").note
    assert "push from m1:" in note


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


def test_a_push_on_a_cell_member_measures_that_member_not_the_cells_box():
    """The pushed item is u2, one member of the stamped cell 'sensor' -
    u3 sits far enough from u2 within the cell's own generated layout that
    the cell's aggregate body box centre and u2's own point are nowhere
    near each other: the note must give u2's distance, not the box's."""
    from placemat.values import Cell
    fps = [footprint("M1", 10, 10, w=2, h=2, inst="m1", nets=("A", "GND")),
           footprint("U2", 1, 1, w=2, h=2, inst="sensor.u2", nets=("SIG", "GND"), cell="sensor"),
           footprint("U3", 15, 1, w=2, h=2, inst="sensor.u3", nets=("SIG2", "GND"), cell="sensor")]
    b = Board(board_geometry(fps, cells=["sensor"], width=80, height=80), edge_margin=1.0)
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Cell("sensor"), radius=30.0, step=1.0)
    b.push(Part("sensor.u2"), from_=Part("m1"), falloff=3, reference=(2.0, 3.2), limit=0.3)
    plan = b.resolve()
    p = plan.pushes[0]
    placement = plan.step("sensor").placement
    occ = plan.occupancy
    from placemat.layout import _target_point
    u2_point = _target_point(occ, plan._items["sensor"], placement, "U2")
    box_centre = occ.body_box(plan._items["sensor"], placement).center
    assert u2_point.distance(box_centre) > 1.0     # the two points are genuinely different here
    assert p.achieved_mm == pytest.approx(Location(10, 10).distance(u2_point), abs=0.01)


def _replay_push_board(r5_radius=3.0):
    """m1, a pushed u2 (linked to j1 so it is not the only thing settled),
    and r5 declared after it: changing r5's OWN search radius (not its
    generated geometry) changes the digest from r5's step on, so a reuse
    replays m1/j1/u2 exactly and re-searches only r5 and the cleanup pass
    - the scenario a partial replay actually faces in practice."""
    fps = [footprint("M1", 10, 30, w=4, h=4, inst="m1", nets=("A", "GND")),
           footprint("U2", 15, 30, w=2, h=2, inst="u2", nets=("SIG", "GND")),
           footprint("J1", 16, 30, w=2, h=2, inst="j1", nets=("SIG", "PWR")),
           footprint("R5", 50, 5, w=2, h=2, inst="r5", nets=("X", "Y"))]
    b = Board(board_geometry(fps, width=60, height=60), edge_margin=1.0)
    b.place(Part("m1"), at=Location(10, 30))
    b.place(Part("j1"), at=Location(16, 30))
    b.link(PadRef(Part("u2"), "SIG"), PadRef(Part("j1"), "SIG"), weight=1)
    b.place(Part("u2"), radius=20.0, step=0.25)
    b.push(Part("u2"), from_=Part("m1"), falloff=1, reference=(2.0, 3.2), limit=0.9, why="field")
    b.place(Part("r5"), radius=r5_radius)
    return b


def test_a_replayed_run_still_enforces_the_hard_limit_through_cleanup():
    """_replay_settle skips _settle (and so _reserve_pushes) entirely: the
    push's disc is a reservation, not a commit, so nothing but a fresh
    _reserve_pushes call puts it back. Without it, the cleanup pass that
    follows a changed-item replay (cleanup is not itself replayed once
    anything after this item changed) sees no reservation at all and is
    free to pull u2 inside its own hard limit."""
    first = _replay_push_board().resolve()
    u2_first = first.box("u2").center.distance(Location(10, 30))
    reused = _replay_push_board(r5_radius=6.0).resolve(reuse=first.reuse)
    assert reused.reuse["reused"] > 0 and reused.reuse["first_change"] == "r5"    # a genuine partial replay
    u2_reused = reused.box("u2").center.distance(Location(10, 30))
    assert u2_reused == pytest.approx(u2_first, abs=1e-6)


def test_a_falloff_too_small_for_its_reference_and_limit_is_refused():
    """r_ref * (v_ref/limit) ** (1/falloff) has no finite value once
    falloff is tiny enough: a clear ValueError at declaration, not an
    OverflowError raised deep inside resolve()."""
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"))
    with pytest.raises(ValueError, match="falloff"):
        b.push(Part("u2"), from_=Part("m1"), falloff=0.001, reference=(13.5, 3.2), limit=0.3)


def test_push_cannot_hold_an_item_back_from_itself():
    b = _board()
    b.place(Part("m1"), at=Location(10, 10))
    b.place(Part("u2"))
    with pytest.raises(ValueError, match="itself"):
        b.push(Part("u2"), from_=Part("u2"), falloff=3, reference=(13.5, 3.2), limit=0.3)
