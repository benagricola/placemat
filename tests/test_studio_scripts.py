"""placemat studio: which Python files are layout scripts, what a board is called, and switching the script watched."""
import http.client
import json
import time
from pathlib import Path

import pytest

from placemat.project import find_board
from placemat.studio import Studio, declares_board, layout_scripts, project_root, script_titles
from tests import real_modules


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    script = real_modules.stage(tmp_path_factory.mktemp("scripts"), "usbconverter")
    return script


def test_a_file_that_calls_board_as_it_loads_is_a_layout_script_and_a_helper_of_functions_is_not(tmp_path):
    layout = tmp_path / "x_layout.py"
    layout.write_text('from placemat import board\nif True:\n    board.place(1)\n')
    helper = tmp_path / "helper.py"
    helper.write_text("def frame(board, k):\n    board.plane(k)\n\nclass A:\n    def f(self, board):\n        board.place(2)\n")
    nothing = tmp_path / "plain.py"
    nothing.write_text("x = 1\n")
    broken = tmp_path / "broken.py"
    broken.write_text("board.place(\n")
    named = tmp_path / "y_layout.py"
    named.write_text("# named like a layout script, but it lays nothing out\nX = 1\n")
    assert declares_board(layout) and not declares_board(helper) and not declares_board(nothing)
    assert not declares_board(broken) and not declares_board(named)             # the file's name decides nothing


def test_the_project_lists_every_layout_script_under_its_root_and_not_the_helper_beside_them(project):
    src = find_board(project)
    root = project_root(src.board_dir)
    found = layout_scripts(root)
    names = sorted(p.name for p, _ in found)
    assert names == ["LogicSupply_layout.py", "Usb5v_layout.py", "UsbConverter_layout.py"]
    assert (root / "fragment_frame.py").is_file() and "fragment_frame.py" not in names


def test_a_board_is_named_by_what_placemat_knows_it_as_with_the_docstrings_first_line_as_its_subtitle(project):
    src = find_board(project)
    title, sub = script_titles(project, src)
    assert title == "UsbConverter"
    assert sub.startswith("the ") and not sub.lower().startswith("usbconverter")       # "UsbConverter: the ..." loses its name
    plain = project.parent / "Plain_layout.py"
    plain.write_text("from placemat import board\nboard.place(1)\n")
    assert script_titles(plain, src) == ("UsbConverter", "")
    folder = type("Src", (), {"name": "", "board_dir": project.parent})()
    assert script_titles(plain, folder)[0] == project.parent.name                       # the folder's name when there is no board name
    plain.unlink()


@pytest.fixture
def studio(project):
    s = Studio(project, port=0, open_browser=False, debounce_ms=50, poll_ms=50)
    s._initial = False                          # no resolve: these tests are about which script is watched
    s.sent = []
    s.worker.send = lambda cmd: s.sent.append(cmd) or True
    s.start()
    yield s
    s.stop()


def _post(studio, path, body, token=True):
    conn = http.client.HTTPConnection("127.0.0.1", studio.port, timeout=10)
    conn.request("POST", path + ("?t=" + studio.token if token else ""), body=json.dumps(body), headers={"Content-Type": "application/json"})
    r = conn.getresponse()
    out = r.read()
    conn.close()
    return r.status, out


def _wait_scripts(studio):
    import time
    end = time.monotonic() + 20
    while studio._scripts is None and time.monotonic() < end:
        time.sleep(0.05)
    assert studio._scripts is not None


def test_the_hello_names_the_board_and_lists_the_layout_scripts(studio):
    _wait_scripts(studio)
    hello = json.loads(studio.hello()[0][1])
    assert hello["title"] == "UsbConverter" and hello["subtitle"]
    assert [s["id"].split("/")[-1] for s in hello["scripts"]] == ["LogicSupply_layout.py", "Usb5v_layout.py", "UsbConverter_layout.py"]
    assert [s["title"] for s in hello["scripts"] if s["current"]] == ["UsbConverter"]


def test_switching_needs_the_token_and_a_listed_layout_script_and_changes_only_what_is_watched(studio):
    _wait_scripts(studio)
    other = next(s["id"] for s in studio.script_list() if s["title"] == "Usb5v")
    assert _post(studio, "/switch", {"script": other}, token=False)[0] == 403
    assert _post(studio, "/switch", {"script": "../../etc/passwd"})[0] == 400
    assert _post(studio, "/switch", {"script": "fragment_frame.py"})[0] == 400            # a helper is not a layout script
    assert _post(studio, "/elsewhere", {"script": other})[0] == 405
    q = studio.hub.subscribe(lambda: [])
    before = studio.script
    assert _post(studio, "/switch", {"script": other})[0] == 200
    assert studio.script != before and studio.script.name == "Usb5v_layout.py"
    deadline = time.monotonic() + 5
    while not studio.sent and time.monotonic() < deadline:     # the next tick resolves the new script
        time.sleep(0.02)
    assert studio.sent
    name, text = q.get(timeout=5)
    data = json.loads(text)
    assert name == "switched" and data["title"] == "Usb5v" and [s["current"] for s in data["scripts"]].count(True) == 1
    assert studio.history == type(studio.history)(maxlen=studio.history.maxlen)             # nothing of the old script is kept
    assert any(f.name == "Usb5v_layout.py" for f in studio._files)                           # and the new one is what is watched


def test_resolve_again_is_a_token_guarded_post_with_an_optional_fresh(studio):
    _wait_scripts(studio)
    assert _post(studio, "/resolve", {"fresh": True}, token=False)[0] == 403
    before = len(studio.sent)
    status, body = _post(studio, "/resolve", {"fresh": True})
    assert status == 200 and json.loads(body) == {"fresh": True}
    deadline = time.monotonic() + 5
    while len(studio.sent) == before and time.monotonic() < deadline:
        time.sleep(0.02)
    assert studio.sent[-1]["cmd"] == "resolve" and studio.sent[-1]["fresh"] is True
