"""Suggestions about a Centre: the flag's notice is cleared by removing the keyword; a coordinate placement is turned
toward intent where a relation can be measured; an intent Centre may slide along its line."""
from placemat import suggestions as sg
from placemat.findings import FindingCause as C
from tests.suggest_support import apply_and_resolve, resolve

PRE = '''board.place(Part("c1"), at=Location(40, 40))
'''


def of(plan, cause):
    return [f for f in plan.findings if f.cause is cause]


def test_a_default_flag_is_removed_by_a_suggestion_that_leaves_the_rest_of_the_centre(tmp_path):
    body = PRE + 'board.place(Part("u1"), at=Centre(X(PadRef(Part("c1"), 1)), 12, coordinates=False))\n'
    board, plan, path = resolve(tmp_path, body, imports=_imports())
    (f,) = of(plan, C.SETUP_CENTRE_FLAG_DEFAULT)
    (s,) = f.suggestions
    assert s.text == "Leave coordinates=False out of the Centre of u1"
    sg.apply_suggestion([s], s.id, root=tmp_path, log=tmp_path / "applied.jsonl")
    assert 'at=Centre(X(PadRef(Part("c1"), 1)), 12))' in path.read_text()
    assert "coordinates" not in path.read_text()


def test_a_coordinate_placement_is_offered_a_relation_and_never_the_flag(tmp_path):
    body = PRE + 'board.place(Part("u1"), at=Centre(40, 36))\n'
    board, plan, path = resolve(tmp_path, body, imports=_imports())
    (f,) = of(plan, C.SETUP_CENTRE_COORDINATES)
    assert f.facts["relation"]["item"] == "c1"
    texts = [s.text for s in f.suggestions]
    assert texts and all(t.startswith("Place u1 beside c1, on its ") for t in texts)
    assert not any("coordinates=True" in str(s.to_json()) for s in f.suggestions)
    board2, plan2 = apply_and_resolve(tmp_path, plan, f.suggestions[0].id, path)
    assert not of(plan2, C.SETUP_CENTRE_COORDINATES) and plan2.placement("u1") is not None
    assert "Beside(Part(" in path.read_text() and "Centre(" not in path.read_text()


def test_a_numeric_centre_with_nothing_to_relate_to_gets_no_suggestion(tmp_path):
    board, plan, path = resolve(tmp_path, 'board.place(Part("u1"), at=Centre(30, 12))\n', imports=_imports())
    (f,) = of(plan, C.SETUP_CENTRE_COORDINATES)
    assert f.suggestions == ()


def _imports():
    from tests.suggest_support import IMPORTS
    return IMPORTS.replace("Turns)", "Turns, X, Y)")
