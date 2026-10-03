"""The studio's edge: sentences for the page are made from records, with the renderers the console uses; what crosses a socket or a pipe
holds none."""
import json

from placemat import channel, present, probe, step_text
from placemat.refusals import Code, Refusal
from placemat.step_text import record
from tests.test_preview_json import _plan
from placemat.preview_json import declared_sites, plan_json


def test_a_plan_document_has_no_sentence_of_the_engines_and_the_page_is_given_them():
    b, plan = _plan()
    doc = plan_json(plan, declared_sites(b))
    assert all("text" not in f for f in doc["findings"]) and all("note" not in s for s in doc["steps"] + doc["items"])
    assert all("why" not in r for r in doc["reservations"]) and all(isinstance(r["by"], dict) for r in doc["reservations"])
    assert all(isinstance(n, dict) and n["kind"] in step_text.RENDER for s in doc["steps"] for n in s["notes"])
    assert not any("text" in v for f in doc["findings"] for v in [f["facts"]])
    shown = present.plan(doc)
    assert all(f["text"] for f in shown["findings"]) and all(isinstance(s["note"], str) for s in shown["steps"])
    assert [u["why"] for u in shown["unplaced"]] and all(isinstance(u["reasons"], list) for u in shown["unplaced"])
    assert all(isinstance(r["why"], str) and r["why"] for r in shown["reservations"])
    assert "text" not in doc["findings"][0]                                 # the original is left alone
    json.dumps(shown)


def test_every_note_of_a_resolved_step_renders_and_is_json():
    b, plan = _plan()
    for s in plan.steps:
        for n in s.notes:
            assert n["kind"] in step_text.RENDER and json.loads(json.dumps(n)) == n
        assert isinstance(s.note, str)
        if s.unplaced is not None:
            assert json.loads(json.dumps(list(s.unplaced))) == list(s.unplaced) and "UNPLACED" in s.note


def test_a_note_gets_the_parts_the_page_labels():
    refusal = Refusal(Code.VIA_BAN, ban="the ring keepout", net="GND", at=[1.0, 2.0]).to_json()
    shown = present.notes([
        record("moved_off_hint", mm=1.0, why=refusal), record("moved_off_hint", mm=1.0, for_score=True),
        record("where", where={"form": "line", "axis": "x", "at_mm": 26.5, "toward": "north"}),
        record("push", source="L1", value=2.5, at_mm=3.0, limit=8.0),
        record("rank", rank=1, of=3, area_mm2=4.0, area_rank=2, pins=2, pins_rank=3),
        record("vias", facts={"nets": [{"net": "GND", "parts": [{"kind": "share", "n": 6}, {"kind": "drop", "n": 1}], "under": ["U3"], "held": []}],
                              "fields": [{"net": "GND", "pad": ["U1", "2"], "way": "route", "before": 4, "after": 3, "want": 4, "under": []}]})])
    assert shown[0]["why_text"] == str(Refusal.from_json(refusal)) and shown[0]["text"].startswith("moved 1.00 mm off the hint: ")
    assert shown[1]["why_text"] == "for a better link score"
    assert (shown[2]["head"], shown[2]["tail"]) == ("on the line x = 26.50", "as far north as it is legal")
    assert shown[3]["detail"] == "2.5 at 3.0 mm, limit 8" and shown[4]["area_ord"] == "2nd" and shown[4]["pins_ord"] == "3rd"
    lines = shown[5]["lines"]
    assert [(l["n"], l["warn"]) for l in lines] == [(6, True), (None, False)] and lines[0]["text"].startswith("GND vias shared, 1 dropped under U3")
    assert shown[5]["text"] == "vias: " + "; ".join(("%d " % l["n"] if l["n"] is not None else "") + l["text"] for l in lines)


def test_an_error_event_is_a_record_and_its_words_come_from_failure_text():
    cases = [
        ({"kind": "exception", "type": "ValueError", "detail": "bad", "file": "a.py", "line": 3}, "ValueError: bad", "error: ValueError: bad (a.py:3)"),
        ({"kind": "run_failure", "failure": "script", "detail": "NameError: x"}, "Layout script failed: NameError: x", None),
        ({"kind": "run_failure", "failure": "placement", "item": "u1", "detail": "u1 has no place"}, "u1 has no place", None),
        ({"kind": "run_failure", "failure": "generation", "detail": ""}, "Schematic generation failed", None),
        ({"kind": "probe_refused", "code": "finding_gone", "id": "s1"}, None, None),
        ({"kind": "lost", "last": {"ev": "item", "key": "u1", "kind": "part", "notes": [record("lock_held")]}},
         "the command stopped without saying it was done (last: u1 part: held by lock)", None),
        ({"kind": "died"}, "the command died without saying it was done", None),
        ({"kind": "cannot_follow", "detail": "refused"}, "cannot follow: refused", None),
    ]
    for ev, text, line in cases:
        ev = dict(ev, ev="error")
        assert "message" not in ev
        if text is not None:
            assert channel.failure_text(ev) == text
        if line is not None:
            assert channel.describe(ev) == line
        shown = present.event(ev)
        assert shown["message"] == channel.failure_text(ev) and "message" not in ev


def test_why_the_cached_generation_is_stale_is_a_record_and_a_failure_names_its_stage():
    from placemat.runner import RunFailure, stale_text
    assert stale_text(None) == "" and stale_text({"form": "no_record"}) == "no record of the files it was generated from"
    assert stale_text({"form": "changed", "files": ["a", "b", "c", "d", "e"]}) == "a, b, c, d and 1 more changed since it was generated"
    assert RunFailure("script", "Layout script failed", {"error": "NameError: x", "line": 3}).record() == {"failure": "script", "detail": "NameError: x"}
    assert RunFailure("escape", "u1 pin 3 cannot escape").record() == {"failure": "escape", "detail": "u1 pin 3 cannot escape"}
    assert RunFailure("placement", "Firm placements collide; fix the script").record() == {"failure": "placement", "detail": ""}
    assert RunFailure("placement", "u1 found no place", {"item": "u1"}).record() == {"failure": "placement", "item": "u1", "detail": "u1 found no place"}


def test_a_stop_record_is_rendered_by_failure_text_too():
    ev = {"ev": "error", "kind": "stopped", "signal": "SIGTERM", "stage": "explore", "command": "explore"}
    assert channel.failure_text(ev) == "explore stopped by SIGTERM during explore"


def test_the_probes_events_carry_a_refusal_and_an_error_as_records():
    r = probe.ProbeRefused("base_failed", error={"kind": "timeout", "limit_s": 5.0})
    assert r.record == {"code": "base_failed", "error": {"kind": "timeout", "limit_s": 5.0}}
    assert "does not resolve" in str(r) and "5 s" in str(r)
    done = present.event({"ev": "probe_done", "state": "error", "refusal": r.record})
    assert done["message"] == str(r)
    cand = present.event({"ev": "candidate", "error": {"kind": "exception", "type": "ValueError", "detail": "x"}})
    assert cand["error_text"] == "ValueError: x"
    assert probe.Candidate.from_json({"value": 1, "error": "an older sentence"}).error == {"kind": "exception", "type": "", "detail": "an older sentence"}


def test_a_route_off_reason_is_a_record_and_the_page_gets_its_words():
    ev = {"ev": "route_off", "reason": {"code": "no_function", "module": "pcb_modification", "name": "add_route_to_pcb_data"}}
    assert present.event(ev)["why"] == "pcb_modification has no add_route_to_pcb_data"
    assert channel.describe(ev) == "no progress for this route: pcb_modification has no add_route_to_pcb_data"


def test_the_events_format_is_in_the_hello_and_a_models_why_is_a_word():
    assert channel.FORMAT == 2
    assert present.model_why({"why": "not_found", "text": "${KIPRJMOD}/x.step"}) == "model not found: ${KIPRJMOD}/x.step"
    assert present.model_why({"why": "unreadable", "detail": "denied"}) == "model cannot be read: denied"
