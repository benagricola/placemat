"""A searched part or cell standing at a turn that another turn its `rotations=` allow, at the same spot and legal there,
clearly beats on its links' pad-to-pad length or crossings: a `turn.better` notice, judged once on the finished board,
with a suggestion that writes the turn into the script."""
import dataclasses

import pytest

from placemat import lock as L
from placemat import suggestions as sg
from placemat.board_geometry import Footprint
from placemat.context import run_script
from placemat.findings import FindingCause as C
from placemat.layout import Board
from placemat.settings import Settings
from placemat.values import Box, Face, Location
from tests.fixtures import board_geometry, footprint, pad
from tests.suggest_support import IMPORTS, script, suggestions_of


def column(ref, inst, x, nets):
    """A part with a column of pads at x, 2 mm apart, pin 1 north."""
    pads = tuple(pad(ref, inst, k + 1, n, x, 24.0 + 2.0 * k, 0.8, 0.6) for k, n in enumerate(nets))
    body = Box(x - 0.8, 23.2, x + 0.8, 26.8)
    return Footprint(ref, inst, None, ref, Location(x, 25.0), 0.0, Face.FRONT, body, body.inflate(0.1), body, pads)


def parts():
    """U1 west and J1 east, each a column of two pins; the cell `term` holds two series resistors between them, one
    above the other, U1's side (pad 1) west."""
    return [column("U1", "u1", 17.0, ("A1", "A2")), column("J1", "j1", 33.0, ("B1", "B2")),
            footprint("R1", 25, 24, w=2.2, h=0.8, nets=("A1", "B1"), cell="term", inst="term.r1"),
            footprint("R2", 25, 26, w=2.2, h=0.8, nets=("A2", "B2"), cell="term", inst="term.r2")]


BODY = '''board.place(Part("u1"), at=Location(17, 25))
board.place(Part("j1"), at=Location(33, 25))
board.place(Cell("term"), at=Near(Location(25, 25)), radius=3.0, rotations=(0, 180))
for k in (1, 2):
    board.link(PadRef(Part("u1"), k), PadRef(Part("term.r%d" % k), 1), weight=LinkWeight.SHORT)
    board.link(PadRef(Part("term.r%d" % k), 2), PadRef(Part("j1"), k), weight=LinkWeight.PREFER)
'''


def board(tmp_path, body=BODY, _copper=(), **settings):
    path = script(tmp_path, body, imports=IMPORTS.replace("(board, ", "(board, Cell, "))
    b = Board(board_geometry(parts(), cells=["term"], width=50, height=50, copper=_copper), edge_margin=1.0, keep_going=True,
              settings=dataclasses.replace(Settings(), cleanup_enabled=False, **settings))
    b.script_file = str(path)
    run_script(path, b)
    return b, path


def locked_at(tmp_path, rotation, body=BODY, **settings):
    """The board resolved with `term` held by a lock entry at `rotation`, where the plain search put it."""
    b, _ = board(tmp_path, body, **settings)
    at = b.resolve().placement("term")
    b, path = board(tmp_path, body, **settings)
    intent = next(i for i in b._placements() if i.key == "term")
    entry = L.LockEntry("term", None, None, (at.location.x, at.location.y), rotation, "front", L.declaration_digest(b, intent))
    plan = b.resolve(lock=[entry])
    assert plan.step("term").lock == "held"
    return plan, path


def turns(plan, item=None) -> list:
    """The turn.better findings, of `item` (the cell or the resistor a test is about) by default: the fixed parts either
    side of it have their own."""
    keys = {"term", "r1"} if item is None else {item}
    return [f for f in plan.findings if f.cause is C.TURN_BETTER and f.facts["item"] in keys]


def test_the_search_left_alone_takes_the_turn_its_links_favour_and_says_nothing(tmp_path):
    b, _ = board(tmp_path)
    plan = b.resolve()
    assert plan.placement("term").rotation == 0.0
    assert turns(plan) == []


def test_a_cell_held_at_the_reversed_turn_is_a_notice_naming_the_turn_its_links_favour(tmp_path):
    """The lock holds the cell turned half round: each U1 side faces J1, so the SHORT links from U1 run past the
    resistors and both bundles cross. Turned back, at the same spot, the SHORT links shorten and the crossings go."""
    plan, _ = locked_at(tmp_path, 180.0)
    (f,) = turns(plan)
    assert f.severity == "notice" and f.kind == "turn"
    facts = f.facts
    assert (facts["item"], facts["kind"], facts["rotation_deg"], facts["to_deg"], facts["turn_deg"]) == \
        ("term", "cell", 180.0, 0.0, 180.0)
    assert facts['change']['crossings'] < 0 and facts['change']['link'] < 0 and facts['rotations_given']
    assert facts['gain'] == pytest.approx(-sum(facts['change'].values()), abs=0.01)


def test_largest_signed_terms_are_said_in_magnitude_order():
    from placemat.finding_text import render
    facts = {"item": "u3", "kind": "part", "rotation_deg": 90.0, "to_deg": 270.0, "turn_deg": 180.0,
             "change": {'link': -3.0, 'airwire': 0.5, 'crossings': -8.0}, 'gain': 10.5}
    assert render(C.TURN_BETTER, facts) == \
        "part u3 turned 180 degrees, to 270 degrees: gain 10.5 (crossings -8, link -3)"


def test_a_locked_item_is_held_by_the_lock_and_its_suggestion_is_the_lock_release(tmp_path):
    """Nothing is applied: the turn is the lock's, and the advice names the command that releases the entry."""
    plan, path = locked_at(tmp_path, 180.0)
    (f,) = turns(plan)
    assert f.facts["held_by"] == "lock"
    (s,) = f.suggestions
    assert s.how == "advice" and s.edits == () and s.advice == {"release": ["term"], "to_deg": 0.0}
    assert s.text == ("Turn cell term to 0 degrees: its turn is held by the lock; release it with "
                      "`placemat lock <script> --release term` and the next run searches it again")


def test_a_narrowed_rotations_is_judged_over_every_turn_and_the_suggestion_narrows_it_again(tmp_path):
    body = BODY.replace("rotations=(0, 180)", "rotations=(180,)")
    b, path = board(tmp_path, body)
    plan = b.resolve()
    assert plan.placement("term").rotation == 180.0
    (f,) = turns(plan)
    assert f.facts["to_deg"] == 0.0 and "held_by" not in f.facts
    (s,) = f.suggestions
    assert s.text == "Turn cell term to 0 degrees"
    shown = sg.apply_suggestion(suggestions_of(plan), s.id, dry_run=True)
    assert 'board.place(Cell("term"), at=Near(Location(25, 25)), radius=3.0, rotations=[0])' in shown.files[str(path)].after


PARTS = '''board.place(Part("u1"), at=Location(17, 25))
board.place(Part("j1"), at=Location(33, 25))
board.link(PadRef(Part("u1"), 1), PadRef(Part("r1"), 1), weight=LinkWeight.SHORT)
board.link(PadRef(Part("r1"), 2), PadRef(Part("j1"), 1), weight=LinkWeight.PREFER)
'''


def part_board(tmp_path, line, imports_extra=""):
    """U1 and J1 as above, and one series resistor R1 between them (U1 side pad 1) placed by `line`."""
    fps = [column("U1", "u1", 17.0, ("A1", "A2")), column("J1", "j1", 33.0, ("B1", "B2")),
           footprint("R1", 25, 24, w=2.2, h=0.8, nets=("A1", "B1"), inst="r1")]
    path = script(tmp_path, PARTS + line + "\n", imports=IMPORTS.replace("(board, ", "(board, " + imports_extra))
    b = Board(board_geometry(fps, width=50, height=50), edge_margin=1.0, keep_going=True,
              settings=dataclasses.replace(Settings(), cleanup_enabled=False))
    b.script_file = str(path)
    run_script(path, b)
    return b.resolve(), path


def test_a_fixed_part_turned_by_rotation_is_judged_and_its_suggestion_edits_the_value_as_a_constant(tmp_path):
    plan, path = part_board(tmp_path, 'board.place(Part("r1"), at=Location(25, 24), rotation=180)')
    (f,) = turns(plan)
    assert (f.facts["item"], f.facts["rotation_deg"], f.facts["to_deg"]) == ("r1", 180.0, 0.0)
    (s,) = f.suggestions
    assert s.text == "Turn part r1 to 0 degrees"
    after = sg.apply_suggestion(suggestions_of(plan), s.id, dry_run=True).files[str(path)].after
    assert "rotation=R1_ROTATION_DEG)" in after and "R1_ROTATION_DEG = 0" in after


def test_a_fixed_part_with_no_rotation_is_judged_at_every_right_angle(tmp_path):
    """Generated reversed: nothing in the script turns it, so every right-angle turn is asked."""
    fps_turned = 'board.place(Part("r1"), at=Location(25, 24))'
    plan, _ = part_board(tmp_path, fps_turned.replace("Location(25, 24))", "Location(25, 24), rotation=90)"))
    (f,) = turns(plan)
    assert f.facts["rotation_deg"] == 90.0 and f.facts["to_deg"] == 0.0


def test_a_why_that_names_the_turn_holds_it(tmp_path):
    plan, _ = part_board(tmp_path, 'board.place(Part("r1"), at=Location(25, 24), rotation=180, '
                                   'why="turned so its silk reads from the south")')
    (f,) = turns(plan)
    assert f.facts["held_by"] == "why" and f.suggestions == ()


def test_a_rotation_by_facing_holds_the_turn(tmp_path):
    plan, _ = part_board(tmp_path, 'board.place(Part("r1"), at=Location(25, 24), rotation=Facing(PadRef(Part("r1"), 1), Edge.EAST))',
                         imports_extra="Facing, ")
    (f,) = turns(plan)
    assert f.facts["held_by"] == "facing" and f.suggestions == ()


def test_a_part_at_the_turn_its_links_favour_is_no_finding(tmp_path):
    plan, _ = part_board(tmp_path, 'board.place(Part("r1"), at=Location(25, 24), rotation=0)')
    assert turns(plan) == []


def test_a_gain_under_the_settings_is_no_finding(tmp_path):
    plan, _ = locked_at(tmp_path, 180.0, place_turn_gain_mm=1000.0)
    assert turns(plan) == []


def test_an_item_the_pin_study_turns_is_left_to_that_advice(tmp_path, monkeypatch):
    monkeypatch.setattr(Board, "_pin_study_turned", lambda self, plan: {"R1"})
    plan, _ = locked_at(tmp_path, 180.0)
    assert turns(plan) == []


def test_crossing_price_controls_the_common_gain_threshold(tmp_path):
    weights = dict(score_congestion=0.0, score_escape_crossed=0.0, score_escape_closed=0.0,
                   score_escape_via=0.0, score_link=0.0)
    high, _ = locked_at(tmp_path, 180.0, score_crossing=20.0, place_turn_gain_mm=50.0, **weights)
    low, _ = locked_at(tmp_path, 180.0, score_crossing=0.0, place_turn_gain_mm=50.0, **weights)
    assert turns(high)
    assert turns(low) == []
    assert turns(high)[0].facts['change']['crossings'] < -50


def test_crossings_alone_can_trigger_a_turn_without_wire_length_gain(tmp_path):
    from placemat.values import CopperLayer, Net
    body = BODY.replace('at=Near(Location(25, 25)), radius=3.0, rotations=(0, 180)',
                        'at=Location(25, 25), rotation=180')
    def resolve(price):
        b, _ = board(tmp_path, body, score_crossing=price, score_crossing_plane=1.0,
                     score_link=0.0, score_congestion=0.0, score_escape_crossed=0.0,
                     score_escape_closed=0.0, score_escape_via=0.0, place_turn_gain_mm=50)
        for net in ('A1', 'A2', 'B1', 'B2'):
            b.plane(Net(net), [CopperLayer.B])
        return b.resolve()
    high, low = resolve(20), resolve(0)
    (finding,) = turns(high)
    assert finding.facts['change']['airwire'] == 0
    assert finding.facts['change']['link'] == 0
    assert finding.facts['change']['crossings'] < -50
    assert turns(low) == []


def test_linkless_turn_can_reduce_fitted_area_and_restores_exact_occupancy():
    from placemat import score
    from placemat.values import Part
    fps = [footprint('R1', 10, 10, w=6, h=1, nets=('', ''), inst='r1'),
           footprint('R2', 40, 10, w=1, h=1, nets=('', ''), inst='r2')]
    b = Board(board_geometry(fps), keep_going=True,
              settings=dataclasses.replace(Settings(), cleanup_enabled=False, place_turn_gain_mm=0.01,
                                           place_turn_gain_share=0.0))
    b.rect(fit=True, margin=5)
    b.place(Part('r1'), at=Location(10, 10), rotation=90)
    b.place(Part('r2'), at=Location(40, 10), rotation=0)
    plan = b.resolve()
    (finding,) = turns(plan, 'r1')
    assert finding.facts['change']['area'] < 0
    assert finding.facts['change']['airwire'] == 0
    occ = plan.occupancy
    before = (dict(occ.items), tuple(occ.copper), frozenset(occ.pending), score.whole(b, occ, plan))
    plan.findings = [f for f in plan.findings if f.cause is not C.TURN_BETTER]
    b._report_turns(occ, plan)
    after = (dict(occ.items), tuple(occ.copper), frozenset(occ.pending), score.whole(b, occ, plan))
    assert after == before


@pytest.mark.parametrize('pending', [{'R1'}, {'term'}])
def test_turn_check_preserves_preexisting_member_or_parent_lift(tmp_path, monkeypatch, pending):
    b, _ = board(tmp_path)
    plan = b.resolve()
    intent = next(i for i in b._placements() if i.key == 'term')
    monkeypatch.setattr(b, '_placements', lambda: [intent])
    occ = plan.occupancy
    occ.lift(pending)
    before = (frozenset(occ.pending), dict(occ.items), tuple(occ.copper))
    b._report_turns(occ, plan)
    assert (frozenset(occ.pending), dict(occ.items), tuple(occ.copper)) == before
    occ.unlift(pending)


def test_turn_check_restores_occupancy_when_delta_raises(tmp_path, monkeypatch):
    from placemat import score, score_delta
    from tests.test_cell_drops import _via
    b, _ = board(tmp_path, _copper=[_via('A1', 25, 25, 'term')])
    plan = b.resolve()
    intent = next(i for i in b._placements() if i.key == 'term')
    monkeypatch.setattr(b, '_placements', lambda: [intent])
    occ = plan.occupancy
    assert any(s.owner == 'term' for s in occ.copper)
    before = (frozenset(occ.pending), dict(occ.items), tuple(occ.copper), score.whole(b, occ, plan))
    def fail(*args, **kwargs):
        raise RuntimeError('injected score failure')
    monkeypatch.setattr(score_delta, 'Delta', fail)
    with pytest.raises(RuntimeError, match='injected score failure'):
        b._report_turns(occ, plan)
    assert (frozenset(occ.pending), dict(occ.items), tuple(occ.copper), score.whole(b, occ, plan)) == before


def test_cheaper_turn_cannot_increase_walled_pad_evidence(tmp_path, monkeypatch):
    from placemat import score_delta
    body = BODY.replace('at=Near(Location(25, 25)), radius=3.0, rotations=(0, 180)',
                        'at=Location(25, 25), rotation=180')
    b, _ = board(tmp_path, body)
    plan = b.resolve()
    assert turns(plan)
    real_delta = score_delta.Delta
    class WithNewWall:
        def __init__(self, *args, **kwargs):
            self.delta = real_delta(*args, **kwargs)
            self.base = None
        def __call__(self, placement):
            result = self.delta(placement)
            if self.base is None:
                self.base = result
                return result
            return dataclasses.replace(result, walled=self.base.walled + 1)
    monkeypatch.setattr(score_delta, 'Delta', WithNewWall)
    plan.findings = [f for f in plan.findings if f.cause is not C.TURN_BETTER]
    b._report_turns(plan.occupancy, plan)
    assert turns(plan) == []
