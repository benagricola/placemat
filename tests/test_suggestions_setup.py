"""setup, escape, fixed and slide cases on synthetic scripts."""

from placemat import suggestions as sg
from tests.fixtures import footprint
from tests.suggest_support import apply_and_resolve, resolve, suggestions_of
from tests.test_escape_findings import _walled_in


def of(plan, case):
    return [f for f in plan.findings if f.cause == case]


UNDECLARED = '''board.place(Part("u1"), at=Location(10, 10))
board.place(Part("c1"), at=Location(40, 40))
board.place(Part("c4"), at=Location(40, 45))
board.place(Part("r1"), at=Location(40, 50))
'''


def test_a_part_no_declaration_places_is_offered_a_searched_place_after_the_last_one(tmp_path):
    board, plan, path = resolve(tmp_path, UNDECLARED)
    (f,) = of(plan, "setup.undeclared")
    (s,) = f.suggestions
    assert s.text == "Place j1 searched from its links"
    shown = sg.apply_suggestion(suggestions_of(plan), s.id, dry_run=True).files[str(path)].after
    assert shown.endswith('board.place(Part("r1"), at=Location(40, 50))\nboard.place(Part("j1"))\n')


def test_placing_the_undeclared_part_clears_the_finding(tmp_path):
    board, plan, path = resolve(tmp_path, UNDECLARED)
    (f,) = of(plan, "setup.undeclared")
    board2, plan2 = apply_and_resolve(tmp_path, plan, f.suggestions[0].id, path)
    assert not of(plan2, "setup.undeclared") and plan2.placement("j1") is not None


FIXED = '''board.place(Part("u1"), at=Location(30, 30))
board.place(Part("c1"), at=Location(30, 30))
board.place(Part("c4"), at=Location(50, 50))
board.place(Part("r1"), at=Location(50, 20))
board.place(Part("j1"), at=Location(10, 10))
'''


def test_a_decided_part_that_is_not_legal_offers_to_search_it_or_take_the_other_face(tmp_path):
    board, plan, path = resolve(tmp_path, FIXED)
    fs = of(plan, "fixed.part")
    assert fs
    texts = [s.text for s in fs[0].suggestions]
    assert any(t.startswith("Let ") and t.endswith(" be searched") for t in texts)
    assert any(t.startswith("Take ") and t.endswith(" on the back face") for t in texts)


def test_letting_the_part_be_searched_clears_the_finding(tmp_path):
    board, plan, path = resolve(tmp_path, FIXED)
    f = of(plan, "fixed.part")[0]
    s = next(s for s in f.suggestions if s.lever == "search")
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path)
    assert not of(plan2, "fixed.part")


def test_taking_the_back_face_clears_the_finding(tmp_path):
    board, plan, path = resolve(tmp_path, FIXED)
    f = of(plan, "fixed.part")[0]
    s = next(s for s in f.suggestions if s.lever == "face")
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path)
    assert not of(plan2, "fixed.part")


WALLED = '''board.place(Part("u9"), at=Location(30, 30))
board.place(Part("r9"), at=Location(30, 30))
board.place(Part("t1"), at=Location(50, 50))
'''


def test_a_walled_pad_offers_a_fanout_on_its_side_and_a_lane(tmp_path):
    board, plan, path = resolve(tmp_path, WALLED, parts=_walled_in(0.1))
    (f,) = of(plan, "escape_walled")
    texts = [s.text for s in f.suggestions]
    assert any(t.startswith("Keep u9's ") and t.endswith(" side clear") for t in texts) or "Keep the lane of u9 pin 1 clear" in texts
    assert "Keep the lane of u9 pin 1 clear" in texts
    s = next(s for s in f.suggestions if s.lever == "escape")
    shown = sg.apply_suggestion(suggestions_of(plan), s.id, dry_run=True).files[str(path)].after
    assert 'board.escape(Part("u9"), [1], why="keeps the way out of u9 pin 1 clear (escape_walled)")' in shown


def test_a_fanout_suggestion_is_a_statement_the_script_runs(tmp_path):
    board, plan, path = resolve(tmp_path, WALLED, parts=_walled_in(0.1))
    (f,) = of(plan, "escape_walled")
    fan = [s for s in f.suggestions if s.lever == "fanout"]
    if fan:
        board2, plan2 = apply_and_resolve(tmp_path, plan, fan[0].id, path, parts=_walled_in(0.1))
        assert plan2.placement("u9") is not None


def test_a_slide_that_finds_no_room_offers_the_other_edges(tmp_path):
    parts = [footprint("U1", 10, 10, w=30, h=6, inst="u1", nets=("A", "B")),
             footprint("C1", 10, 10, w=30, h=6, inst="c1", nets=("A", "B")),
             footprint("C4", 10, 10, w=30, h=6, inst="c4", nets=("A", "B"))]
    script = ('board.place(Part("u1"), at=OnEdge(Edge.NORTH))\nboard.place(Part("c1"), at=OnEdge(Edge.NORTH))\n'
              'board.place(Part("c4"), at=OnEdge(Edge.NORTH))\n')
    board, plan, path = resolve(tmp_path, script, parts=parts, width=50, height=50)
    fs = of(plan, "unplaced.slide")
    assert fs
    texts = [s.text for s in fs[0].suggestions]
    assert texts == ["Put %s on the %s edge" % (fs[0].facts["item"], e) for e in ("south", "east", "west")]
    s = fs[0].suggestions[0]
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path, parts=parts, width=50, height=50)
    assert fs[0].facts["item"] not in [f.facts["item"] for f in of(plan2, "unplaced.slide")]


def test_a_bearing_search_that_finds_none_offers_nothing(tmp_path):
    script = ('board.place(Part("u1"), at=Location(30, 30))\n'
              'board.place(Part("j1"), at=Location(30, 30), rotations=[0, 90])\n'
              'board.place(Part("c1"), at=Location(50, 50))\n')
    board, plan, path = resolve(tmp_path, script)
    fs = of(plan, "unplaced.bearing")
    assert fs and [s.text for s in fs[0].suggestions] == []
