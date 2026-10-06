"""A finished route in the studio: its copper and its open nets, from the run's own files, whether the route is looked at as a past
run, as a run's build, as a route record or as the command that made it."""
import json

import pytest

from placemat import route_progress
from placemat.studio import Studio
from tests import real_modules
from tests.test_studio_picker import _board_dirs, _run_folder
from tests.test_studio_server import _get

RID = "ab12cd34"
SEG_A = [[1.0, 1.0, 5.0, 1.0, "F.Cu", 0.2], [5.0, 1.0, 5.0, 4.0, "B.Cu", 0.2]]
VIA_A = [[5.0, 1.0, 0.45, 0.2, ["F.Cu", "B.Cu"]]]
DRC_AFTER = {"unconnected_items": [
    {"description": "Missing connection between items", "severity": "error", "type": "unconnected_items",
     "items": [{"description": "Pad 1 [B] of R1 on F.Cu", "pos": {"x": 2.0, "y": 6.0}}, {"description": "Pad 2 [B] of R2 on F.Cu", "pos": {"x": 8.0, "y": 6.0}}]}]}


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return real_modules.stage(tmp_path_factory.mktemp("routed"), "usbconverter")


def _studio(project):
    s = Studio(None, port=0, open_browser=False, root=project.parents[2])
    s.worker.send = lambda cmd: pytest.fail("a finished route is looked at, not resolved")
    s.m3d.submit = lambda jobs: len(jobs)
    return s


def _routed_run(s, rid=RID, events=None, drc=True):
    """A run that routed: its record (net A routed, net B not), its placement (plan.json) and the DRC after the route. The record's board
    path names the project's layout file, which is not the run's copy."""
    board_dir = _board_dirs(s)[0]
    script = next(e["path"] for e in s.scripts() if e["src"].board_dir == board_dir)
    folder = _run_folder(board_dir, rid, script)
    (folder / "route").mkdir()
    (folder / "plan.json").write_text(json.dumps({"board": {"loops": [[[0, 0], [10, 0], [10, 8], [0, 8]]], "drawn": True, "extent": [0, 0, 10, 8]}, "items": [], "layers": ["F.Cu", "B.Cu"],
                                                   "steps": [], "copper": []}))
    if events is None:
        events = [{"ev": "queue", "nets": ["A", "B"]}, {"ev": "net_begin", "net": "A"}, {"ev": "net_end", "net": "A", "ok": True},
                  {"ev": "commit", "net": "A", "how": "route", "seg": SEG_A, "via": VIA_A}, {"ev": "net_begin", "net": "B"}, {"ev": "net_end", "net": "B", "ok": False},
                  {"ev": "queue_end"}]
    stages = [{"stage": "main", "resumed": False, "complete": True, "dropped": 0, "seconds": 1.0, "events": events}]
    project_pcb = board_dir / "layout" / "layout.kicad_pcb"
    route_progress.write_record(folder / "route", {"run": rid, "script": str(script), "pcb": str(project_pcb), "doc": route_progress.BOARD}, stages,
                                {"closure": 0.5, "open_before": 2, "open_after": 1, "open_nets": {"B": 1}}, complete=True)
    if drc:
        (folder / "route" / "drc_after.json").write_text(json.dumps(DRC_AFTER))
    return folder


def _routed(doc):
    return [c for c in doc["copper"] if c.get("origin") == "routed" and c.get("x") is None]


def test_a_past_run_that_routed_is_served_with_its_routed_copper_and_open_nets_from_its_own_record(project):
    s = _studio(project)
    folder = _routed_run(s)
    for doc in (s.build_record(RID)["doc"], s.run_view(RID)["doc"], s.route_record(str(folder / "route" / route_progress.RECORD))["doc"]):
        assert [(c["t"], c["net"]) for c in _routed(doc)] == [("track", "A"), ("track", "A"), ("via", "A")]
        assert doc["open"] == [{"net": "B", "a": [2.0, 6.0], "b": [8.0, 6.0]}]
        assert doc["route"]["open"] == 1 and doc["route"]["unread"] is None and (doc["route"]["routed"], doc["route"]["failed"]) == (1, 1)
    assert s.run_view(RID)["summary"]["id"] == RID


def test_the_endpoints_a_page_calls_for_a_past_routed_run_and_for_the_command_that_made_it(project):
    s = _studio(project)
    _routed_run(s, rid="ab12cd35")
    s.start()
    try:
        for path in ("/build?run=ab12cd35", "/runview?run=ab12cd35"):
            st, body = _get(s, path)
            doc = json.loads(body)["doc"]
            assert st == 200 and len(_routed(doc)) == 3 and doc["open"][0]["net"] == "B", path
        s._on_channel(9, {"ev": "hello", "pid": 4009, "command": "run", "script": str(s.root / "x_layout.py"), "args": ["--route"]})
        s._on_channel(9, {"ev": "done", "record": str(_board_dirs(s)[0] / ".placemat" / "runs" / "ab12cd35" / "run.json")})
        st, body = _get(s, "/cmd/9")
        assert st == 200 and json.loads(body)["summary"]["build"] == "ab12cd35"          # the run whose build the page reads once the command is done
    finally:
        s.stop()


def test_a_command_that_ran_no_route_or_wrote_no_run_names_no_build(project):
    s = _studio(project)
    s._on_channel(3, {"ev": "hello", "pid": 4003, "command": "run", "script": str(s.root / "x_layout.py"), "args": []})
    assert s.cmd_detail(3)["summary"]["build"] is None
    _run_folder(_board_dirs(s)[0], "ab12cd36", "x_layout.py")
    s._on_channel(3, {"ev": "done", "record": str(_board_dirs(s)[0] / ".placemat" / "runs" / "ab12cd36" / "run.json")})
    assert s.cmd_detail(3)["summary"]["build"] is None                                   # the run did not route


def test_the_project_layout_file_the_record_names_is_never_read_for_the_copper(project):
    s = _studio(project)
    _routed_run(s, rid="ab12cd37")
    board_dir = _board_dirs(s)[0]
    pcb = board_dir / "layout" / "layout.kicad_pcb"
    before = s.build_record("ab12cd37")["doc"]
    saved = pcb.read_bytes() if pcb.is_file() else None
    try:
        pcb.parent.mkdir(parents=True, exist_ok=True)
        pcb.write_text("(kicad_pcb (version 20240108) changed after the run)")         # reverted or edited since the run
        after = s.build_record("ab12cd37")["doc"]
    finally:
        if saved is not None:
            pcb.write_bytes(saved)
    assert _routed(after) == _routed(before) and after["open"] == before["open"]


def test_a_record_whose_events_carry_no_copper_says_so(project):
    s = _studio(project)
    events = [{"ev": "net_begin", "net": "A"}, {"ev": "net_end", "net": "A", "ok": True}]
    _routed_run(s, rid="ab12cd38", events=events, drc=False)
    doc = s.run_view("ab12cd38")["doc"]
    assert _routed(doc) == [] and doc["route"]["unread"] == {"code": "no_copper", "nets": 1} and doc["open"] == []


def test_a_run_whose_route_record_cannot_be_read_says_so_and_shows_its_placement(project):
    s = _studio(project)
    folder = _routed_run(s, rid="ab12cd39")
    (folder / "route" / route_progress.RECORD).write_text("{not json")
    view = s.run_view("ab12cd39")
    assert view["doc"]["route"]["unread"] == {"code": "record_unreadable"} and view["doc"]["copper"] == []
