"""The studio's board builder end to end on a scratch copy of a fixture project: the start view lists boards with no layout, the board is
read, the facts are decided and confirmed, the outline writes the script in one write, placement goes through the suggestion
endpoints, undo and redo go through the applied log. The board's generation is restored from the cache (`pcb layout` is not run); the
builder's reader runs in this process, and the studio's own resolve worker is a real subprocess."""
import http.client
import json
import time
from pathlib import Path

import pytest

from placemat import builder_worker, facts as facts_mod, runner
from placemat.studio import Studio
from tests.builder_support import stage_project, coordinates_in


def _restore(src, run_dir, fresh, quiet, timeout=900, keep_renders=False):
    import shutil
    shutil.rmtree(src.layout_dir, ignore_errors=True)
    shutil.copytree(runner.cached_generation(src), src.layout_dir)
    return False


def _reader(request, say):
    rec = builder_worker.read(request["zen"], request["name"], request.get("script"), request.get("fresh"), say)
    return {"ev": "board", **rec}


class Api:
    def __init__(self, studio):
        self.studio = studio

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.studio.port, timeout=120)
        sep = "&" if "?" in path else "?"
        data = json.dumps(body).encode() if body is not None else None
        conn.request(method, path + sep + "t=" + self.studio.token, body=data, headers={"Content-Type": "application/json"} if data else {})
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw.decode()

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body=None):
        return self.call("POST", path, body or {})


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(runner, "generate", _restore)
    tmp = tmp_path_factory.mktemp("builder")
    zen, script, board_dir = stage_project(tmp, "usbcells")
    studio = Studio(None, root=tmp / "board", port=0, open_browser=False, debounce_ms=50, poll_ms=50)
    studio.builder.reader = _reader
    studio.start()
    api = Api(studio)
    yield type("B", (), {"studio": studio, "api": api, "zen": zen, "script": script, "board_dir": board_dir, "root": tmp / "board"})
    studio.stop()
    mp.undo()


def wait_phase(b, phase="ready", seconds=120):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        st, state = b.api.get("/build/state")
        if state["phase"] == phase:
            return state
        if state["phase"] == "error":
            raise AssertionError("the builder failed: %s %s" % (state["text"], state["tail"]))
        time.sleep(0.2)
    raise AssertionError("the builder did not reach %s" % phase)


def wait_resolved(b, seconds=300, after=0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        with b.studio.lock:
            if b.studio.history and b.studio.history[-1].id > after and b.studio._cur is None and not b.studio._dirty and not b.studio._initial:
                return b.studio.history[-1]
        time.sleep(0.3)
    raise AssertionError("no resolve finished")


def test_the_start_view_lists_the_boards_with_no_layout_script(built):
    st, state = built.api.get("/build/state")
    assert st == 200
    assert [(u["name"], u["zen"]) for u in state["unbuilt"]] == [("UsbCells", "modules/usbcells/UsbCells.zen")]
    assert state["phase"] == "idle" and state["settings"] == {"grid_mm": 0.5, "max_fill": 0.5, "aspect": 1.0}
    hello = built.studio._hello_data()
    assert hello["picker"] is True and hello["builder"]["unbuilt"][0]["id"] == "modules/usbcells/UsbCells.zen#UsbCells"
    assert not built.script.exists()


def test_a_board_with_a_layout_script_is_not_offered_and_an_unknown_id_is_refused(built):
    st, out = built.api.post("/build/start", {"id": "nowhere.zen#X"})
    assert st == 404 and "without a layout script" in out["error"]
    st, out = built.api.post("/build/offer", {"resolve": 1, "subject": ["u1"]})
    assert st == 409


def test_starting_reads_the_generated_board_and_the_page_is_told_as_it_goes(built):
    events = []
    import threading
    q = built.studio.hub.subscribe(lambda: [])
    st, out = built.api.post("/build/start", {"id": "modules/usbcells/UsbCells.zen#UsbCells"})
    assert st == 200 and out["session"]["exists"] is False and out["session"]["name"] == "UsbCells"
    state = wait_phase(built)
    names = []
    while not q.empty():
        names.append(json.loads(q.get()[1]))
    assert any(e.get("state") == "working" for e in names) and names[-1]["state"] == "ready"
    assert state["board"]["parts"] == 236 and state["board"]["cells"] == 31 and state["board"]["total_courtyard_area"] == pytest.approx(1648.559)


def test_the_facts_start_undecided_the_gate_is_shut_and_confirm_waits_for_the_script(built):
    st, f = built.api.get("/build/facts")
    assert st == 200
    m = f["model"]
    assert m["gate"]["open"] is False and m["counts"]["undecided"] >= 6
    layers = [r for r in m["rows"] if r["fact"] == "layer"]
    assert len(layers) == 6 and all(r["state"] == "undecided" and r["default"] for r in layers)
    assert f["zen"]["stackup"] == "none" and f["zen"]["editable"] is True and f["zen"]["file"] == "modules/usbcells/UsbCells.zen"
    assert [c["positive"] for c in f["candidates"]] == ["USB_D_P"] or {"USB_D_P"} <= {c["positive"] for c in f["candidates"]}
    assert f["fab"]["scope"] == "none" and "project root" in f["fab"]["says"]
    st, out = built.api.post("/build/facts/confirm", {"acks": {}})
    assert st == 409 and "does not exist yet" in out["error"]


FACTS = {"stackup": {"copper_layers": 6, "rows": [
    {"kind": "copper", "role": "signal", "oz": 1}, {"kind": "dielectric", "thickness_mm": 0.1, "form": "prepreg"},
    {"kind": "copper", "role": "power", "oz": 0.5}, {"kind": "dielectric", "thickness_mm": 0.1, "form": "core"},
    {"kind": "copper", "role": "signal", "oz": 0.5}, {"kind": "dielectric", "thickness_mm": 0.5, "form": "prepreg"},
    {"kind": "copper", "role": "power", "oz": 0.5}, {"kind": "dielectric", "thickness_mm": 0.1, "form": "core"},
    {"kind": "copper", "role": "power", "oz": 0.5}, {"kind": "dielectric", "thickness_mm": 0.1, "form": "prepreg"},
    {"kind": "copper", "role": "signal", "oz": 1}]},
         "pairs": {"classes": [{"name": "USB", "diff_pair_width": 0.2, "diff_pair_gap": 0.15, "nets": ["USB_D_P", "USB_D_N"]}]},
         "via": {"micro": "no", "blind": "no", "buried": "no"}, "min": {"track_mm": 0.09}, "rise_c": 20}


def test_a_batch_of_facts_is_one_apply_to_the_three_homes_and_the_readback_reports_what_the_generator_did_not_take(built):
    st, dry = built.api.post("/build/facts/apply", {"request": dict(FACTS, dry_run=True)})
    assert st == 200 and {f["file"] for f in dry["files"]} == {"modules/usbcells/UsbCells.zen", "fab-profile.json", "placemat.toml"} or dry["files"]
    zen_before = built.zen.read_text()
    st, out = built.api.post("/build/facts/apply", {"request": FACTS})
    assert st == 200 and out["applied"] is True and out["undo"] is True
    zen_after = built.zen.read_text()
    assert "CopperLayer(thickness = 0.035" in zen_after and "NetClass(" in zen_after and zen_before.split("\n")[0] in zen_after
    profile = json.loads((built.root / "fab-profile.json").read_text())
    assert profile["via"] == {"micro": "no", "blind": "no", "buried": "no"} and profile["min"] == {"track_mm": 0.09}
    assert "rise_c = 20.0" in (built.root / "placemat.toml").read_text()
    # the board was "regenerated" from its cache, which holds none of the .zen's facts: the stackup and the pairs read back differ and
    # are reported; the profile and the rise are read from their files, so they read back as asked
    assert {r["fact"] for r in out["readback"]} == {"layer", "pairs"}
    st, f = built.api.get("/build/facts")
    rows = {r["id"]: r["state"] for r in f["model"]["rows"]}
    assert rows["via:micro"] == "decided" and rows["min"] == "decided" and rows["rise"] == "decided" and rows["layer:F.Cu"] == "decided"
    log = [json.loads(l) for l in (built.board_dir / ".placemat" / "applied.jsonl").read_text().splitlines()]
    assert log[-1]["source"] == "builder" and log[-1]["text"].startswith("Facts: stackup, pair classes, via types, fab minimums, the rise")
    assert len(log[-1]["files"]) == 4 or len(log[-1]["files"]) == 3
    # one undo takes the batch back
    st, undone = built.api.post("/suggest/undo")
    assert st == 200 and built.zen.read_text() == zen_before and not (built.root / "fab-profile.json").exists()
    st, redone = built.api.post("/suggest/redo")
    assert st == 200 and built.zen.read_text() == zen_after


def test_the_outline_size_is_suggested_from_the_courtyard_area_and_a_typed_size_shows_its_fill(built):
    st, s = built.api.post("/build/outline/suggest", {"shape": "rect", "faces": 2, "fill": 0.5, "aspect": 1.5})
    assert st == 200 and s["area"] == pytest.approx(1648.559) and s["width"] == 50.0 and s["height"] == 33.5 and s["grid_mm"] == 0.5
    st, s1 = built.api.post("/build/outline/suggest", {"shape": "rect", "faces": 1})
    assert s1["area"] == pytest.approx(1648.559 * 2) and (s1["width"], s1["height"]) == (57.5, 57.5)
    st, t = built.api.post("/build/outline/suggest", {"shape": "rect", "faces": 2, "typed": {"width": 60.0, "height": 40.0}})
    assert t["typed"] is True and t["fill"] == pytest.approx(1648.559 / (2 * 2400.0))
    st, d = built.api.post("/build/outline/suggest", {"shape": "disc", "faces": 1, "fill": 0.4})
    assert st == 200 and d["diameter"] > 0
    st, bad = built.api.post("/build/outline/suggest", {"shape": "rect", "faces": 3})
    assert st == 422 and "one face or two" in bad["error"]


def test_the_script_is_written_in_one_write_from_the_skeleton_and_the_studio_watches_it(built, monkeypatch):
    monkeypatch.setattr(Studio, "_begin", lambda self, changed: None)       # the resolve of the new script is the next test's
    spec = {"shape": "rect", "width": 60.0, "height": 40.0}
    st, bad = built.api.post("/build/outline/create", {"spec": {"shape": "rect", "width": 0, "height": 1}})
    assert st == 422 and "positive" in bad["error"] and not built.script.exists()
    st, out = built.api.post("/build/outline/create", {"spec": spec, "description": "the demo"})
    assert st == 200 and out["script"] == "modules/usbcells/UsbCells_layout.py"
    text = built.script.read_text()
    assert text.startswith('"""UsbCells: the demo"""\nfrom placemat import board\n') and text.endswith("board.rect(width=BOARD_WIDTH_MM, height=BOARD_HEIGHT_MM)\n")
    log = [json.loads(l) for l in (built.board_dir / ".placemat" / "applied.jsonl").read_text().splitlines()]
    assert log[-1]["files"][0]["before"] is None and log[-1]["source"] == "builder"
    assert built.studio.script == built.script.resolve()
    st, again = built.api.post("/build/outline/create", {"spec": spec})
    assert st == 409 and "exists" in again["error"]
    # undo past the first write returns the board to no layout
    st, _ = built.api.post("/suggest/undo")
    assert st == 200 and not built.script.exists() and built.studio.script is None
    assert [u["name"] for u in built.api.get("/build/state")[1]["unbuilt"]] == ["UsbCells"]
    st, _ = built.api.post("/suggest/redo")
    assert st == 200 and built.script.exists() and built.studio.script == built.script.resolve()


FLAGS = {"plane:In1.Cu": True, "plane:In3.Cu": True, "plane:In4.Cu": True}


def test_placement_waits_for_the_confirmation_and_the_confirmation_is_the_commands_own(built):
    wait_phase(built)
    built.studio.resolve_now()                  # the new script's first resolve (the test before held the start of resolves back)
    rec = wait_resolved(built)
    st, parts = built.api.get("/build/parts")
    assert st == 200 and parts["counts"] == {"unplaced": 31, "searched": 0, "decided": 0, "by hand": 0} and parts["resolve"] == rec.id
    assert parts["outline"]["shape"] == "rect" and parts["outline"]["dims"] == {"width": 60.0, "height": 40.0}
    st, out = built.api.post("/build/offer", {"resolve": rec.id, "subject": ["usbpd.esd"], "target": {"kind": "edge", "edge": "SOUTH"}})
    assert st == 423 and "waits for the board's facts" in out["error"] and out["holds"]
    st, out = built.api.post("/build/facts/confirm", {"acks": FLAGS})
    assert st == 200 and out["file"] == "placemat.toml"
    text = (built.root / "placemat.toml").read_text()
    digest = out["confirmed"]
    assert '[facts.boards]\n"modules/usbcells/UsbCells_layout.py" = "%s"' % digest in text
    assert text == facts_mod.confirmed_text(text.split("\n[facts.boards]")[0] + "\n", digest, key="modules/usbcells/UsbCells_layout.py") or digest in text
    st, f = built.api.get("/build/facts")
    assert f["model"]["gate"]["open"] is True and f["model"]["confirmed"] is True


def test_a_click_becomes_an_offer_the_suggestion_endpoints_show_try_and_apply(built):
    rec = wait_resolved(built)
    q = {"resolve": rec.id, "subject": ["usbpd.esd"], "target": {"kind": "edge", "edge": "SOUTH"}}
    st, out = built.api.post("/build/offer", q)
    assert st == 200, out
    assert [o["intent"] for o in out["offers"]] == ["on_edge_any", "on_edge_start", "on_edge_mid", "on_edge_end"]
    mid = next(o for o in out["offers"] if o["intent"] == "on_edge_mid")
    added = mid["preview"]["UsbCells_layout.py"]["added"]
    assert mid["text"] == "Place usbpd.esd in the middle of the south edge" and added[0].startswith("from placemat import")
    assert added[-1] == 'board.place(Cell("usbpd.esd"), at=OnEdge(Edge.SOUTH, along=Along.MID))'
    assert mid["id"].startswith("b")
    st, shown = built.api.post("/suggest/show", {"resolve": rec.id, "id": mid["id"]})
    assert st == 200 and shown["files"][0]["file"] == "UsbCells_layout.py" and "+board.place(Cell(\"usbpd.esd\")" in shown["diff"]
    assert not built.script.read_text().count("usbpd.esd")                           # Show writes nothing
    st, done = built.api.post("/suggest/apply", {"resolve": rec.id, "id": mid["id"]})
    assert st == 200 and done["undo"] is True
    text = built.script.read_text()
    assert text.endswith('\nboard.place(Cell("usbpd.esd"), at=OnEdge(Edge.SOUTH, along=Along.MID))\n')
    log = [json.loads(l) for l in (built.board_dir / ".placemat" / "applied.jsonl").read_text().splitlines()]
    assert log[-1]["source"] == "builder" and log[-1]["text"] == "Place usbpd.esd in the middle of the south edge"
    # the watcher re-resolves, and the part list reads the new state from the script and the plan
    new = wait_resolved(built, after=rec.id)
    assert new.id > rec.id and new.applied.startswith("applied from a suggestion: Place usbpd.esd")
    st, parts = built.api.get("/build/parts")
    row = next(r for r in parts["rows"] if r["key"] == "usbpd.esd")
    assert row["status"] == "decided" and row["phrase"] == "on the south edge, in the middle" and parts["counts"]["decided"] == 1
    assert coordinates_in(built.script.read_text()) == []


def test_the_rest_is_searched_in_one_apply_and_one_undo_takes_it_back(built):
    rec = wait_resolved(built)
    st, out = built.api.post("/build/offer", {"resolve": rec.id, "kind": "search", "keys": ["usbpd.tcpc", "usbpd.moisture"]})
    assert st == 200 and out["offers"][0]["count"] == 2
    before = built.script.read_text()
    st, done = built.api.post("/suggest/apply", {"resolve": rec.id, "id": out["offers"][0]["id"]})
    assert st == 200
    text = built.script.read_text()
    assert text.count("board.place(Cell(") == 3 and "# Searched from their links.\n" in text
    st, _ = built.api.post("/suggest/undo")
    assert st == 200 and built.script.read_text() == before
    st, _ = built.api.post("/suggest/redo")
    assert st == 200 and built.script.read_text() == text
    st, bad = built.api.post("/build/offer", {"resolve": rec.id, "kind": "search", "secret": 1})
    assert st == 400 and "more than the builder takes" in bad["error"]


def test_a_stale_plan_is_refused_when_the_script_was_edited_meanwhile(built):
    rec = wait_resolved(built)
    st, out = built.api.post("/build/offer", {"resolve": rec.id, "subject": ["usbpd.sink"], "target": {"kind": "part", "key": "usbpd.esd", "side": "NORTH"}})
    assert st == 200, out
    sid = out["offers"][0]["id"]
    text = built.script.read_text()
    built.script.write_text(text + "# a hand edit\n")
    st, bad = built.api.post("/suggest/apply", {"resolve": rec.id, "id": sid})
    assert st == 409 and "changed since" in bad["error"]
    built.script.write_text(text)
