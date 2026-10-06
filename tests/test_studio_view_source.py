"""The code view of a view the page shows in place of a resolve of its own (a followed command, a past run): /viewsource serves the
view's own script, the modules it imports and any other file of the project its plan names by a source link, and nothing outside
the project. A real fixture project, staged as a copy; nothing is resolved."""
import http.client
import json
import os
import time

import pytest

from placemat.report import RunRecord
from placemat.studio import Studio, SuggestRefused
from tests import real_modules

HELPER = "srcview_helper"


@pytest.fixture
def project(tmp_path):
    script = real_modules.stage(tmp_path, "usbconverter", edit=lambda t: "import %s\n" % HELPER + t)
    (script.parent / (HELPER + ".py")).write_text("GAP_MM = 0.2\n")
    return script


@pytest.fixture
def studio(project):
    s = Studio(None, port=0, open_browser=False, root=project.parents[2])
    s.start()
    yield s
    s.stop()


def _get(studio, query):
    from urllib.parse import urlencode
    conn = http.client.HTTPConnection("127.0.0.1", studio.port, timeout=30)
    conn.request("GET", "/viewsource?" + urlencode(dict(query, t=studio.token)))
    r = conn.getresponse()
    data = json.loads(r.read())
    conn.close()
    return r.status, data


def _item(key, file, line):
    return {"key": key, "kind": "part", "placed": True, "file": str(file), "line": line, "members": []}


def _follow(studio, script, items, cid=3):
    studio._on_channel(cid, {"ev": "hello", "pid": 99999999, "command": "preview", "script": str(script), "args": ["preview"]})
    studio._on_channel(cid, {"ev": "plan", "doc": {"items": items, "findings": [], "steps": []}})
    return {"kind": "cmd", "ref": str(cid)}


def test_a_followed_commands_script_its_import_and_a_module_script_its_plan_names_are_served(studio, project):
    module = project.parents[1] / "usb5v" / "Usb5v_layout.py"
    view = _follow(studio, project, [_item("u1", project, 4), _item("cell", module, 2)])
    assert studio.script is None
    code, out = _get(studio, dict(view, file=str(project)))
    assert code == 200 and out["text"] == project.read_text() and out["name"] == project.name and out["changed"] is False, out
    assert out["file"] == str(project)
    names = [f["name"] for f in out["files"]]
    assert names[0] == project.name and HELPER + ".py" in names and "../usb5v/Usb5v_layout.py" in names
    code, out = _get(studio, dict(view, file=str(project.parent / (HELPER + ".py"))))
    assert code == 200 and out["text"] == "GAP_MM = 0.2\n"
    code, out = _get(studio, dict(view, file=str(module)))
    assert code == 200 and out["text"] == module.read_text() and out["name"] == "../usb5v/Usb5v_layout.py"


def test_a_file_changed_since_the_command_started_is_served_and_said_changed(studio, project):
    view = _follow(studio, project, [_item("u1", project, 4)])
    later = time.time() + 60
    os.utime(project, (later, later))
    code, out = _get(studio, dict(view, file=str(project)))
    assert code == 200 and out["changed"] is True and out["text"] == project.read_text()


def test_a_past_runs_script_is_served(studio, project):
    folder = project.parent / ".placemat" / "runs" / "abcd1234"
    folder.mkdir(parents=True)
    (folder / "plan.json").write_text(json.dumps({"items": [_item("u1", project, 4)], "findings": [], "steps": []}))
    RunRecord(run_id="abcd1234", board="UsbConverter", status="ok", paths={"script": str(project)}).save(folder / "run.json")
    old = time.time() - 600
    os.utime(project, (old, old))
    code, out = _get(studio, {"kind": "run", "ref": "abcd1234", "file": str(project)})
    assert code == 200 and out["text"] == project.read_text() and out["changed"] is False, out
    later = time.time() + 60
    os.utime(project, (later, later))
    code, out = _get(studio, {"kind": "run", "ref": "abcd1234", "file": str(project)})
    assert code == 200 and out["changed"] is True


def test_files_outside_the_project_not_of_the_view_or_gone_are_refused_with_a_reason(studio, project, tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET = 1\n")
    helper = project.parent / (HELPER + ".py")
    view = _follow(studio, project, [_item("u1", project, 4), _item("x", outside, 1), _item("h", helper, 1)])
    code, out = _get(studio, dict(view, file=str(outside)))
    assert code == 403 and out["reason"] == "outside" and "SECRET" not in json.dumps(out), out
    for f in ("/etc/passwd", str(project.parent / ".." / ".." / ".." / "outside.py")):
        code, out = _get(studio, dict(view, file=f))
        assert code in (403, 404) and out["reason"] in ("outside", "not_of_view") and "SECRET" not in json.dumps(out), (f, out)
    helper.unlink()
    code, out = _get(studio, dict(view, file=str(helper)))
    assert code == 404 and out["reason"] == "gone" and "no longer there" in out["error"], out
    with pytest.raises(SuggestRefused) as e:
        studio.view_source("cmd", "77", str(project))
    assert e.value.extra["reason"] == "no_view"
