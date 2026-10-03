"""The builder's start: which boards the start view lists, that the named board of a `.zen` that declares several is the one started, and
that a generation failure shows the generator's log tail and writes nothing. The reader is a stand-in: these tests do not generate."""
import time

import pytest

from placemat.studio import Studio
from tests.test_studio_builder import Api


def project(tmp_path):
    (tmp_path / "placemat.toml").write_text("")
    (tmp_path / "two.zen").write_text('Board(name = "Alpha", layout_path = "layout/Alpha")\nBoard(name = "Beta", layout_path = "layout/Beta")\n')
    sub = tmp_path / "modules" / "m"
    sub.mkdir(parents=True)
    (sub / "M.zen").write_text('Layout(name = "M")\nProject(name = "Cell", layout = False)\n')
    (sub / "M_layout.py").write_text('from placemat import board\nboard.rect(fit=True, draw=False)\n')
    (tmp_path / "hidden").mkdir()
    (tmp_path / ".pcb").mkdir()
    (tmp_path / ".pcb" / "std.zen").write_text('Board(name = "Std")\n')
    return tmp_path


@pytest.fixture
def studio(tmp_path):
    root = project(tmp_path)
    s = Studio(None, root=root, port=0, open_browser=False)
    s.requests = []

    def reader(request, say):
        s.requests.append(request)
        say({"stage": "generating", "zen": "x.zen"})
        if request["name"] == "Alpha":
            return {"ev": "error", "kind": "run_failure", "failure": "generation", "detail": "", "tail": "error: unknown module @stdlib/x.zen\nfailed"}
        return {"ev": "board", "parts": [], "cells": [], "nets": [], "total_courtyard_area": 10.0, "copper_layers": 2,
                "facts": {"layers": {}, "pairs": {}, "via_types": {"micro": "no", "blind": "no", "buried": "no"}, "fab_min": {}, "rise_c": 10.0,
                          "plane_mismatches": [], "via_named": [], "digest": "x"}, "confirmed": "", "rise_set": False, "rise_file": "", "fab_file": "",
                "outline_box": []}
    s.builder.reader = reader
    s.start()
    yield s
    s.stop()


def phase(api, want, seconds=20):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        state = api.get("/build/state")[1]
        if state["phase"] == want:
            return state
        time.sleep(0.05)
    raise AssertionError("never %s: %s" % (want, state))


def test_a_board_with_a_script_or_declared_without_a_layout_or_in_a_hidden_folder_is_not_listed(studio):
    got = Api(studio).get("/build/state")[1]["unbuilt"]
    assert [(u["name"], u["zen"]) for u in got] == [("Alpha", "two.zen"), ("Beta", "two.zen")]


def test_the_named_board_of_a_zen_that_declares_several_is_the_one_started(studio):
    api = Api(studio)
    st, out = api.post("/build/start", {"id": "two.zen#Beta"})
    assert st == 200 and out["session"]["name"] == "Beta" and out["session"]["script"] == "Beta_layout.py"
    phase(api, "ready")
    assert studio.requests[-1]["name"] == "Beta" and studio.requests[-1]["script"] is None


def test_a_generation_failure_shows_the_log_tail_and_writes_nothing(studio, tmp_path):
    api = Api(studio)
    before = sorted(p.name for p in tmp_path.rglob("*") if p.is_file())
    api.post("/build/start", {"id": "two.zen#Alpha"})
    state = phase(api, "error")
    assert state["text"] == "Schematic generation failed" and "unknown module" in state["tail"]
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == before
    st, out = api.post("/build/outline/create", {"spec": {"shape": "rect", "width": 10, "height": 10}})
    assert st == 409 and "not read yet" in out["error"]


def test_an_existing_script_is_not_started_again(studio, tmp_path):
    (tmp_path / "Beta_layout.py").write_text("from placemat import board\nboard.rect(width=1, height=1)\n")
    studio.builder.unbuilt(refresh=True)
    st, out = Api(studio).post("/build/start", {"id": "two.zen#Beta"})
    assert st == 404 or st == 409


def test_the_request_may_not_carry_source_or_anything_but_its_documented_keys(studio):
    st, out = Api(studio).post("/build/offer", {"resolve": 1, "subject": ["a"], "source": "board.place(1)"})
    assert st in (400, 409)
    st, out = Api(studio).post("/build/bogus", {})
    assert st == 404
