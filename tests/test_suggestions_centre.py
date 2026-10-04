"""Suggestions about a Centre: the flag's notice is cleared by removing the keyword."""
from placemat import suggestions as sg
from placemat.findings import FindingCause as C
from tests.suggest_support import resolve

PRE = '''board.place(Part("c1"), at=Location(40, 40))
'''


def of(plan, cause):
    return [f for f in plan.findings if f.cause is cause]


def test_a_default_flag_is_removed_by_a_suggestion_that_leaves_the_rest_of_the_centre(tmp_path):
    body = PRE + 'board.place(Part("u1"), at=Centre(X(PadRef(Part("c1"), 1)), None, coordinates=False))\n'
    board, plan, path = resolve(tmp_path, body, imports=_imports())
    (f,) = of(plan, C.SETUP_CENTRE_FLAG_DEFAULT)
    (s,) = f.suggestions
    assert s.text == "Leave coordinates=False out of the Centre of u1"
    sg.apply_suggestion([s], s.id, root=tmp_path, log=tmp_path / "applied.jsonl")
    assert 'at=Centre(X(PadRef(Part("c1"), 1)), None))' in path.read_text()
    assert "coordinates" not in path.read_text()


def _imports():
    from tests.suggest_support import IMPORTS
    return IMPORTS.replace("Turns)", "Turns, X, Y)")
