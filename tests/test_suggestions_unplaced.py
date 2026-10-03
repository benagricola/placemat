"""unplaced cases: suggestions built from what the search measured, and what applying them does."""
from placemat import suggestions as sg
from tests.suggest_support import apply_and_resolve, resolve, suggestions_of

SEARCH = '''board.place(Part("u1"), at=Location(30, 30))
board.place(Part("j1"), at=Near(Location(30, 30), radius=0.5))
board.place(Part("c1"), at=Location(50, 50))
board.place(Part("r1"), at=Location(50, 20))
'''


def unplaced(plan, case=None):
    return [f for f in plan.findings if f.kind == "unplaced" and (case is None or f.cause == case)]


def test_a_search_with_no_legal_spot_offers_the_levers_the_declaration_leaves(tmp_path):
    board, plan, path = resolve(tmp_path, SEARCH)
    (f,) = unplaced(plan, "unplaced.search")
    assert f.startswith("j1:") and f.facts["dominant"]
    texts = [s.text for s in f.suggestions]
    assert any(t.startswith("Place j1 beside ") for t in texts)
    assert "Place j1 before the parts that crowd it" in texts
    assert "Let j1 take the back face too" in texts
    assert "Let j1 turn to any bearing" in texts
    assert not any("radius" in t for t in texts)           # no wider radius: nothing measured says how much
    assert [s.rank for s in f.suggestions] == list(range(1, len(f.suggestions) + 1))
    assert len({s.id for s in f.suggestions}) == len(f.suggestions)


def test_at_most_the_per_lever_limit_of_beside_suggestions(tmp_path):
    board, plan, path = resolve(tmp_path, SEARCH)
    (f,) = unplaced(plan, "unplaced.search")
    assert len([s for s in f.suggestions if s.lever == "beside"]) <= 3


def test_placing_it_beside_a_neighbour_on_a_free_side_places_it(tmp_path):
    board, plan, path = resolve(tmp_path, SEARCH)
    (f,) = unplaced(plan, "unplaced.search")
    s = next(s for s in f.suggestions if s.lever == "beside")
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path)
    assert not unplaced(plan2, "unplaced.search") and plan2.placement("j1") is not None
    assert "at=Beside(Part(" in path.read_text()


def test_taking_the_back_face_too_places_it(tmp_path):
    board, plan, path = resolve(tmp_path, SEARCH)
    (f,) = unplaced(plan, "unplaced.search")
    s = next(s for s in f.suggestions if s.lever == "face")
    board2, plan2 = apply_and_resolve(tmp_path, plan, s.id, path)
    assert not unplaced(plan2, "unplaced.search")
    assert "face=Face.EITHER" in path.read_text()



def test_the_cache_keeps_the_suggestions_of_a_replayed_step(tmp_path):
    """A second resolve that replays the unplaced step still has its suggestions, bound to the script as it is."""
    from tests.suggest_support import make_board
    from placemat.context import run_script
    board, plan, path = resolve(tmp_path, SEARCH)
    again = make_board()
    again.script_file = str(path)
    run_script(path, again)
    plan2 = again.resolve(reuse=plan.reuse)
    (f,) = unplaced(plan2, "unplaced.search")
    assert [s.text for s in f.suggestions] == [s.text for s in unplaced(plan, "unplaced.search")[0].suggestions]
    assert plan2.reuse["reused"] > 0
    # the script's lines moved (a comment line added above): the replayed suggestions bind to the new lines
    path.write_text(path.read_text().replace("board.place(Part(\"u1\")", "# a note\nboard.place(Part(\"u1\")"))
    moved = make_board()
    moved.script_file = str(path)
    run_script(path, moved)
    plan3 = moved.resolve(reuse=plan.reuse)
    (g,) = unplaced(plan3, "unplaced.search")
    s = next(s for s in g.suggestions if s.lever == "face")
    done = sg.apply_suggestion(suggestions_of(plan3), s.id, dry_run=True)
    assert "face=Face.EITHER" in done.files[str(path)].after


POCKET = '''board.place(Part("u1"), at=Location(5, 5))
board.place(Part("c1"))
board.place(Part("j1"), at=Location(30, 30))
'''


def test_a_pocket_case_offers_a_link_a_face_and_a_finer_step(tmp_path):
    parts = [__import__("tests.fixtures", fromlist=["footprint"]).footprint("U1", 5, 5, w=6, h=2, inst="u1", nets=("A", "B")),
             __import__("tests.fixtures", fromlist=["footprint"]).footprint("C1", 20, 20, w=70, h=70, inst="c1", nets=("A", "C")),
             __import__("tests.fixtures", fromlist=["footprint"]).footprint("J1", 30, 30, w=4, h=4, inst="j1", nets=("C", "D"))]
    board, plan, path = resolve(tmp_path, POCKET, parts=parts, width=40, height=40)
    fs = unplaced(plan, "unplaced.pocket")
    assert fs
    texts = [s.text for s in fs[0].suggestions]
    assert any(t.startswith("Pull c1 toward ") for t in texts)
    assert not any("finer step" in t for t in texts)


EDGE = '''board.place(Part("u1"), at=OnEdge(Edge.NORTH))
board.place(Part("c1"), at=OnEdge(Edge.NORTH))
board.place(Part("j1"), at=OnEdge(Edge.NORTH))
'''
