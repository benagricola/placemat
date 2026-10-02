"""The warm resolve: a session that streams a resolve's events, as `placemat preview` resolves."""
import json

import pytest

from placemat.studio_worker import Cancelled, Session
from tests import real_modules


@pytest.fixture(scope="module")
def staged(tmp_path_factory):
    return real_modules.stage(tmp_path_factory.mktemp("studio"), "mcu")


def _run(session, script, n=1):
    events = []
    session.send = events.append
    session.resolve(n, str(script))
    return events


def _kinds(events):
    return [e["ev"] for e in events]


def test_a_resolve_streams_board_items_and_a_finished_plan(staged):
    events = _run(Session(), staged)
    kinds = _kinds(events)
    assert kinds[0] == "board" and kinds[-1] == "done"
    assert kinds.count("item") >= 10
    done = events[-1]
    keys = [e["item"]["key"] for e in events if e["ev"] == "item"]
    assert set(keys) <= {i["key"] for i in done["doc"]["items"]} | {u["item"] for u in done["doc"]["unplaced"]}
    assert done["timing"]["resolve_s"] >= 0 and done["timing"]["first_step_s"] <= done["timing"]["resolve_s"]
    json.dumps(events)                                  # every event is plain JSON


def test_a_second_resolve_replays_what_did_not_change(staged):
    s = Session()
    first = _run(s, staged, 1)[-1]
    second = _run(s, staged, 2)[-1]
    assert second["reused"] and "reused" in second["reused"]
    assert {i["key"]: (i["at"], i["rotation"], i["face"]) for i in first["doc"]["items"]} == \
        {i["key"]: (i["at"], i["rotation"], i["face"]) for i in second["doc"]["items"]}
    assert first["doc"]["findings"] == second["doc"]["findings"]


def test_the_streamed_items_are_the_final_ones_unless_a_later_pass_moved_them(staged):
    events = _run(Session(), staged)
    final = {i["key"]: i for i in events[-1]["doc"]["items"]}
    for e in events:
        if e["ev"] == "item" and e["item"]["placed"] and e["item"]["key"] in final:
            assert e["item"]["file"] == final[e["item"]["key"]]["file"] and e["item"]["line"] == final[e["item"]["key"]]["line"]


def test_a_resolve_asked_to_stop_stops_at_the_next_step_and_says_so(staged):
    s = Session()
    seen = []
    events = []

    def send(ev):
        events.append(ev)
        if ev["ev"] == "item":
            seen.append(ev)
            if len(seen) == 3:
                s.cancel(7)
    s.send = send
    s.resolve(7, str(staged))
    assert events[-1] == {"ev": "cancelled", "id": 7}
    assert "done" not in _kinds(events) and len(seen) == 3


def test_a_cancel_for_another_resolve_is_ignored(staged):
    s = Session()
    s.cancel(99)
    assert _run(s, staged, 1)[-1]["ev"] == "done"


def test_a_script_that_fails_is_an_error_event_with_its_line(staged, tmp_path):
    bad = staged.with_name("Bad_layout.py")
    bad.write_text("from placemat import board\n\nboard.nonsense(1)\n")
    ev = _run(Session(), bad)[-1]
    assert ev["ev"] == "error" and ev["line"] == 3 and "nonsense" in ev["message"]
    bad.unlink()


def test_cancelled_is_not_an_exception_a_script_can_swallow():
    assert not issubclass(Cancelled, Exception)
