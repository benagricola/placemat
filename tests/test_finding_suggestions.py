"""Findings carry a case and suggestions; the suggestion records and the reuse cache keep them."""
import pickle

from placemat import reuse
from placemat.findings import Finding, Findings
from placemat.suggestions import Edit, Suggestion, Target, from_json, to_json


def _suggestion(rank=1, text="Let C4 take the back face too"):
    edit = Edit(op="set_kwarg", target=Target(kind="place", key="C4"), args={"name": "face"},
                value={"enum": "Face.EITHER"})
    return Suggestion(text=text, edit=edit, rank=rank, lever="face")


def test_a_finding_without_a_case_is_as_it_was():
    f = Finding("unplaced", "C4: no room")
    assert f == "C4: no room" and f.kind == "unplaced" and f.severity == "critical"
    assert f.case is None and f.suggestions == () and f.facts == {}


def test_a_case_and_suggestions_change_neither_the_sentence_nor_its_equality():
    plain = Finding("unplaced", "C4: no room")
    rich = Finding("unplaced", "C4: no room", case="unplaced.search", facts={"item": "C4"}, suggestions=[_suggestion()])
    assert rich == plain and str(rich) == str(plain) and rich.severity == plain.severity
    assert rich.case == "unplaced.search" and rich.facts == {"item": "C4"}
    assert [s.text for s in rich.suggestions] == ["Let C4 take the back face too"]


def test_findings_pickle_with_their_case_and_suggestions():
    f = Finding("unplaced", "C4: no room", "warning", case="unplaced.search", facts={"item": "C4"},
                suggestions=[_suggestion()])
    g = pickle.loads(pickle.dumps(f))
    assert (g.kind, str(g), g.severity, g.case, g.facts, g.suggestions) == (f.kind, str(f), "warning", f.case, f.facts,
                                                                           f.suggestions)


def test_suggestions_survive_json():
    s = _suggestion()
    assert Suggestion.from_json(s.to_json()) == s
    assert from_json(to_json([s, _suggestion(2, "x")])) == [s, _suggestion(2, "x")]


def test_the_cache_keeps_the_case_and_the_suggestions():
    f = Finding("unplaced", "C4: no room", case="unplaced.search", facts={"item": "C4"}, suggestions=[_suggestion()])
    stored = reuse.finding_to_json(f)
    assert stored[:3] == ["unplaced", "C4: no room", "critical"] and stored[3] == "unplaced.search"
    g = reuse.finding_from_json(stored)
    assert g == f and g.case == "unplaced.search" and g.suggestions == f.suggestions
    assert g.facts == {}                            # the facts were for building the suggestions


def test_a_three_field_cache_entry_loads_with_none():
    g = reuse.finding_from_json(["unplaced", "C4: no room", "critical"])
    assert g.kind == "unplaced" and g.case is None and g.suggestions == ()
    assert reuse.finding_from_json(["label", "J1: sits on R1"]).case is None


def test_a_finding_without_a_case_stores_as_it_did_with_a_case_of_none():
    stored = reuse.finding_to_json(Finding("setup", "x"))
    assert stored == ["setup", "x", "warning", None, []]
    assert reuse.finding_from_json(stored).suggestions == ()


def test_findings_still_take_only_findings():
    fs = Findings([Finding("setup", "a", case="setup.undeclared")])
    assert fs[0].case == "setup.undeclared"
