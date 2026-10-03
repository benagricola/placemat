"""A search refused by a reservation names its source: the keepout or the label that holds the room."""
from placemat import suggest_facts as sf, suggestions as sg
from tests.suggest_support import IMPORTS, apply_and_resolve, resolve, suggestions_of

KEEPOUT = '''board.keepout(Path([(25, 25), (35, 25), (35, 35), (25, 35)]), "ant", at=Location(30, 30),
              excludes=("parts",), why="an antenna's clearance")
board.place(Part("u1"), at=Location(10, 10))
board.place(Part("j1"), at=Near(Location(30, 30), radius=0.5))
board.place(Part("c1"), at=Location(50, 50))
'''
HEAD = IMPORTS + "from placemat import Path\n"


def search(plan):
    return [f for f in plan.findings if f.cause == "unplaced.search"]


def test_a_search_refused_by_a_keepout_offers_to_let_the_item_in(tmp_path):
    board, plan, path = resolve(tmp_path, KEEPOUT, imports=HEAD)
    (f,) = search(plan)
    assert f.facts["dominant"] == "reservation"
    assert f.facts["reservations"][0]["keepout"] == "ant"
    s = next(s for s in f.suggestions if s.lever == "reservation")
    assert s.text == "Let j1 into keepout `ant`"
    shown = sg.apply_suggestion(suggestions_of(plan), s.id, dry_run=True).files[str(path)].after
    assert 'why="an antenna\'s clearance",\n              allow=[Part("j1")])\n' in shown


def test_letting_the_item_in_places_it(tmp_path):
    board, plan, path = resolve(tmp_path, KEEPOUT, imports=HEAD)
    (f,) = search(plan)
    s = next(s for s in f.suggestions if s.lever == "reservation")
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path)
    assert not search(plan2) and plan2.placement("j1") is not None


def test_the_source_of_a_reservation_is_what_it_was_made_by():
    from placemat.refusals import Owner, ReservedBy
    own = lambda by: Owner("reserved", by=by)
    assert sf.reservation_source(own(ReservedBy("keepout", "ant", "an antenna's clearance"))) == {"keepout": "ant"}
    assert sf.reservation_source(Owner("member_in", "C4", by=ReservedBy("keepout", "ant", "a note"))) == {"keepout": "ant"}
    assert sf.reservation_source(own(ReservedBy("label", "j1 IN", item="j1"))) == {"label": "label j1 IN", "item": "j1"}
    assert sf.reservation_source(own(ReservedBy("fanout", "U1", side="north"))) == {"fanout": "U1"}
    assert sf.reservation_source(own(ReservedBy("other", "something else"))) == {}


def test_a_keepouts_reservation_is_made_by_the_keepout(tmp_path):
    board, plan, path = resolve(tmp_path, KEEPOUT, imports=HEAD)
    why = [r.why for r in plan.occupancy.reservations if "ant" in str(r.why)]
    assert why and why[0].kind == "keepout" and why[0].name == "ant"
