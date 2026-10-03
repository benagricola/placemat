"""Findings carry a cause, facts and suggestions; the suggestion records and the reuse cache keep them."""
import pickle

import pytest

from placemat import finding_text, reuse
from placemat.findings import Finding, FindingCause as C, FindingKind as K, Findings
from placemat.suggestions import Edit, Suggestion, Target, from_json, to_json

FACTS = {"net_class": "Power", "what": "track width", "value_mm": 0.08, "minimum_mm": 0.1, "key": "track"}


def _suggestion(rank=1, text="Let C4 take the back face too"):
    edit = Edit(op="set_kwarg", target=Target(kind="place", key="C4"), args={"name": "face"},
                value={"enum": "Face.EITHER"})
    return Suggestion(text=text, edit=edit, rank=rank, lever="face")


def test_a_finding_is_its_sentence_rendered_from_its_facts():
    f = Finding(C.FAB_MINIMUM, FACTS)
    assert f == finding_text.render(C.FAB_MINIMUM, FACTS)
    assert f.kind is K.FAB and f.cause is C.FAB_MINIMUM and f.severity == "critical"
    assert f.facts == FACTS and f.facts_v == finding_text.facts_version(C.FAB_MINIMUM) and f.suggestions == ()


def test_a_finding_takes_a_cause_not_a_string():
    with pytest.raises(TypeError):
        Finding("fab.minimum", FACTS)


def test_a_missing_fact_is_refused():
    with pytest.raises(Exception):
        Finding(C.FAB_MINIMUM, {"net_class": "Power"})


def test_suggestions_change_neither_the_sentence_nor_its_equality():
    plain = Finding(C.FAB_MINIMUM, FACTS)
    rich = Finding(C.FAB_MINIMUM, FACTS, suggestions=[_suggestion()])
    assert rich == plain and str(rich) == str(plain) and rich.severity == plain.severity
    assert [s.text for s in rich.suggestions] == ["Let C4 take the back face too"]


def test_findings_pickle_with_their_facts_and_suggestions():
    f = Finding(C.FAB_MINIMUM, FACTS, "warning", suggestions=[_suggestion()])
    g = pickle.loads(pickle.dumps(f))
    assert (g.kind, str(g), g.severity, g.cause, g.facts, g.suggestions) == (f.kind, str(f), "warning", f.cause, f.facts,
                                                                           f.suggestions)


def test_suggestions_survive_json():
    s = _suggestion()
    assert Suggestion.from_json(s.to_json()) == s
    assert from_json(to_json([s, _suggestion(2, "x")])) == [s, _suggestion(2, "x")]


def test_the_cache_keeps_the_facts_and_not_the_sentence_or_the_suggestions():
    f = Finding(C.FAB_MINIMUM, FACTS, suggestions=[_suggestion()])
    stored = reuse.finding_to_json(f)
    assert stored == ["fab", "fab.minimum", "critical", finding_text.facts_version(C.FAB_MINIMUM), FACTS]
    g = reuse.finding_from_json(stored)
    assert g == f and g.cause is C.FAB_MINIMUM and g.facts == FACTS and g.suggestions == ()


def test_a_stored_finding_under_another_schema_version_is_refused():
    stored = reuse.finding_to_json(Finding(C.FAB_MINIMUM, FACTS))
    stored[3] += 1
    with pytest.raises(ValueError):
        reuse.finding_from_json(stored)


def test_the_context_key_holds_the_schemas():
    assert finding_text.schemas_digest() and finding_text.schemas_digest() == finding_text.schemas_digest()


def test_findings_still_take_only_findings():
    with pytest.raises(TypeError):
        Findings(["a sentence"])
    assert Findings([Finding(C.FAB_MINIMUM, FACTS)])[0].cause is C.FAB_MINIMUM
