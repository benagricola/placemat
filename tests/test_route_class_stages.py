"""The router spaces every net of one call at the largest clearance among the nets that call routes (KRT
routing_config.py set_net_clearances, the routing-side floor). placemat routes the nets whose clearance is above the
Default's in a stage of their own, one router call per clearance, widest first, before the main pass: each routes at its
own class's clearance, and the main pass's floor is the Default's."""
import json
import sys
import textwrap

import pytest

from placemat.kicad.route import class_stages, routing_clearance
from placemat.settings import Settings, bind
from tests.conftest import needs_kicad
from tests.test_net_halos import FAKE, ROUTER, _two_part_board, needs_router


def test_nets_above_the_default_are_grouped_by_clearance_widest_first():
    clearances = {"RF": 0.2, "RF2": 0.2, "WIDE": 0.3, "EQ": 0.127, "LOW": 0.1, "DONE": 0.25}
    got = class_stages(clearances, 0.127, {"RF", "RF2", "WIDE", "EQ", "LOW", "SIG"})
    assert got == [(0.3, ["WIDE"]), (0.2, ["RF", "RF2"])]
    assert class_stages(clearances, 0.3, {"RF", "WIDE"}) == []
    assert class_stages({}, 0.127, {"RF"}) == []


def test_the_routing_clearance_is_the_routers_default_class_clearance():
    assert routing_clearance(0.15, [], {}) == 0.15
    assert routing_clearance(0.15, ["--clearance", "0.2"], {}) == 0.2
    assert routing_clearance(0.15, ["--clearance=0.1"], {}) == 0.1
    assert routing_clearance(0.15, ["--clearance-ceiling", "0.127"], {}) == 0.127
    assert routing_clearance(0.15, ["--clearance-ceiling", "0.2"], {}) == 0.15


CLASSES = textwrap.dedent('''
    def net_clearance_map_by_id(pcb_path, nets, design_rules=None):
        table = {"VIN": 0.3, "FB": 0.2, "SW": 0.3}
        return {nid: table[name] for nid, name in nets.items() if name in table}
''')


@pytest.fixture
def rig(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    krt = tmp_path / "krt"
    (krt / ".venv/bin").mkdir(parents=True)
    (krt / ".venv/bin/python").symlink_to(sys.executable)
    (krt / "py_router").mkdir()
    (krt / "py_router/route.py").write_text(FAKE)
    (krt / "py_router/list_nets.py").write_text(CLASSES)
    (krt / "VERSION").write_text("fake-1\n")
    monkeypatch.setenv("FAKE_ROUTER_LOG", str(tmp_path / "calls"))

    class Rig:
        pcb = _two_part_board(tmp_path)          # FB and VIN open between U1 and J1; SW one pad and a track
        work = tmp_path / "route"
        router = krt

        def calls(self):
            log = tmp_path / "calls"
            return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

        def route(self, **kw):
            from placemat.kicad.route import route_board
            return route_board(self.pcb, self.work, router_dir_override=str(krt), layers=["F.Cu", "B.Cu"], **kw)
    return Rig()


def _nets(call):
    i = call.index("--nets")
    return call[i + 1:call.index("--layers")]


@needs_kicad
def test_each_clearance_above_the_default_routes_in_its_own_stage_before_the_main_pass(rig):
    report = rig.route(islands={})
    calls = rig.calls()
    assert [_nets(c) for c in calls[:2]] == [["VIN"], ["FB"]]          # 0.3 then 0.2; the Default is 0.15
    main = _nets(calls[2])
    assert main[0] == "*" and {"!VIN", "!FB"} <= set(main) and len(calls) == 3
    # each stage routes on the board the one before it left
    assert calls[1][0] == calls[0][1] and calls[2][0] == calls[1][1]
    assert report.class_stages == [{"clearance_mm": 0.3, "nets": {"VIN": [1, 1]}},
                                   {"clearance_mm": 0.2, "nets": {"FB": [1, 1]}}]
    assert "FB" in report.open_nets and "VIN" in report.open_nets   # the stand-in routes nothing: still open
    d = json.loads((rig.work / "route.json").read_text())
    assert d["class_stages"] == report.class_stages
    assert "class stages: 0.3 mm VIN 1 -> 1; 0.2 mm FB 1 -> 1" in report.summary()


@needs_kicad
def test_an_island_net_is_left_to_its_own_stage_and_a_rerun_resumes_the_class_stages(rig):
    first = rig.route(islands={"VIN": None})
    calls = rig.calls()
    assert [_nets(c) for c in calls[:2]] == [["VIN"], ["FB"]] and _nets(calls[2])[0] == "*" and len(calls) == 3
    assert first.class_stages == [{"clearance_mm": 0.2, "nets": {"FB": [1, 1]}}]
    again = rig.route(islands={"VIN": None})
    assert len(rig.calls()) == 3 and again.resumed == ["islands", "classes", "main"]
    assert again.class_stages == first.class_stages


@needs_kicad
def test_a_halo_net_routes_in_the_stage_of_its_halo(rig):
    """A halo is an entry of the clearance map: the map's value decides the stage."""
    with bind(Settings(route_net_halos={"FB": 1.0})):
        report = rig.route(islands={})
    calls = rig.calls()
    assert [_nets(c) for c in calls[:2]] == [["FB"], ["VIN"]] and len(calls) == 3
    assert {c[c.index("--net-clearances") + 1] for c in calls} == {str(rig.work.resolve() / "net_clearances.json")}
    assert [s["clearance_mm"] for s in report.class_stages] == [1.0, 0.3]


_FLOORS = textwrap.dedent('''
    import json, sys
    from routing_config import GridRouteConfig
    doc = json.load(sys.stdin)
    ids = {n: i + 1 for i, n in enumerate(sorted(doc["map"]) + ["SIG"])}
    out = []
    for stage in doc["stages"] + [["SIG"]]:
        c = GridRouteConfig(clearance=doc["base"])
        c.set_net_clearances({ids[n]: v for n, v in doc["map"].items()}, [ids[n] for n in stage])
        out.append({"floor": c.net_clearance_floor, "prices": {n: c.obstacle_clearance(ids[n]) for n in ids}})
    print("FLOORS " + json.dumps(out))
''')


@needs_router
def test_each_stage_routes_at_its_own_clearance_and_prices_the_earlier_stages_at_theirs():
    """Against the router's own GridRouteConfig: two classes above the Default, each stage's floor is its own clearance,
    earlier stages' copper is priced at its class, and the main pass (SIG) routes at the Default."""
    import subprocess
    clearances = {"RF": 0.2, "ANT": 0.2, "MID": 0.15, "EQ": 0.127}
    stages = class_stages(clearances, 0.127, {"RF", "ANT", "MID", "EQ", "SIG"})
    assert stages == [(0.2, ["ANT", "RF"]), (0.15, ["MID"])]
    proc = subprocess.run([str(ROUTER / ".venv/bin/python"), "-c", _FLOORS], cwd=str(ROUTER / "py_router"), text=True,
                          input=json.dumps({"map": clearances, "base": 0.127, "stages": [n for _, n in stages]}),
                          capture_output=True, timeout=120)
    line = [l for l in proc.stdout.splitlines() if l.startswith("FLOORS ")]
    assert line, proc.stderr[-2000:]
    rf, mid, main = json.loads(line[-1][len("FLOORS "):])
    assert (rf["floor"], mid["floor"], main["floor"]) == (0.2, 0.15, 0.127)
    assert mid["prices"]["RF"] == 0.2 and main["prices"]["RF"] == 0.2 and main["prices"]["MID"] == 0.15
    assert main["prices"]["SIG"] == 0.127


@needs_kicad
def test_a_class_net_already_joined_still_routes_in_its_stage(rig):
    """The router's floor is taken over every net its --nets names with two pads or more, joined or not
    (KRT net_queries.filter_routable_nets): a joined 0.3 mm net in the main pass would space it at 0.3 mm."""
    text = rig.pcb.read_text()
    joined = "".join('\t(segment (start %s) (end %s) (width 0.2) (layer "F.Cu") (net 3))\n' % (a, b)
                     for a, b in (("113 110", "113 112"), ("113 112", "126 112"), ("126 112", "126 110")))
    rig.pcb.write_text(text[:text.rindex(")")] + joined + ")\n")
    report = rig.route(islands={})
    assert [_nets(c) for c in rig.calls()[:2]] == [["VIN"], ["FB"]]
    assert report.class_stages[0] == {"clearance_mm": 0.3, "nets": {"VIN": [0, 0]}}
