"""The router spaces every net of one call at the largest clearance among the nets that call routes (KRT
routing_config.py set_net_clearances, the routing-side floor). A phase routes the nets whose clearance is above the
Default's in a call of their own, one router call per clearance, widest first (kicad/phase_run.py plan_calls): each
routes at its own class's clearance, and the Default-clearance call's floor is the Default's."""
import json
import textwrap

from placemat.kicad.route import clearance_groups, routing_clearance
from tests.conftest import ROUTER, needs_router


def test_nets_above_the_default_are_grouped_by_clearance_widest_first():
    clearances = {"RF": 0.2, "RF2": 0.2, "WIDE": 0.3, "EQ": 0.127, "LOW": 0.1, "DONE": 0.25}
    got = clearance_groups(clearances, 0.127, {"RF", "RF2", "WIDE", "EQ", "LOW", "SIG"})
    assert got == [(0.3, ["WIDE"]), (0.2, ["RF", "RF2"])]
    assert clearance_groups(clearances, 0.3, {"RF", "WIDE"}) == []
    assert clearance_groups({}, 0.127, {"RF"}) == []


def test_the_routing_clearance_is_the_routers_default_class_clearance():
    assert routing_clearance(0.15, [], {}) == 0.15
    assert routing_clearance(0.15, ["--clearance", "0.2"], {}) == 0.2
    assert routing_clearance(0.15, ["--clearance=0.1"], {}) == 0.1
    assert routing_clearance(0.15, ["--clearance-ceiling", "0.127"], {}) == 0.127
    assert routing_clearance(0.15, ["--clearance-ceiling", "0.2"], {}) == 0.15


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
    stages = clearance_groups(clearances, 0.127, {"RF", "ANT", "MID", "EQ", "SIG"})
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
