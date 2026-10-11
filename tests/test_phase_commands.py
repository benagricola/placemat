"""The router calls a phase makes (kicad/phase_run.plan_calls) and their command lines (kicad/route.router_command)."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from placemat.kicad.phase_run import Call, plan_calls, refused_records, write_connections
from placemat.kicad.phase_select import Selection, Task
from placemat.kicad.route import REQUIRES, clearance_groups, router_capable, router_command, router_net_pattern
from placemat.settings import Settings, bind

W5 = (("F.Cu", 0.5), ("B.Cu", 0.5))
W3 = (("F.Cu", 0.3), ("B.Cu", 0.3))


def test_tasks_split_by_clearance_then_width_widest_first():
    tasks = (Task("VB", ("J1", "1"), ("Q1", "1"), W3, 1.0), Task("VB", ("J1", "1"), ("U1", "1"), W5, 4.0),
             Task("HV", ("J2", "1"), ("Q2", "1"), W3, 1.0))
    calls = plan_calls(Selection("p", "connections", tasks=tasks, layers=("F.Cu", "B.Cu")), {"HV": 2.0}, 0.15, set())
    assert [(c.kind, c.clearance, [t.net for t in c.tasks]) for c in calls] == [
        ("tasks", 2.0, ["HV"]), ("tasks", 0.15, ["VB"]), ("tasks", 0.15, ["VB"])]
    assert dict(calls[1].tasks[0].widths)["F.Cu"] == 0.5


def test_task_groups_of_the_same_widest_width_come_in_a_fixed_order():
    a = (("F.Cu", 0.5), ("B.Cu", 0.3))
    b = (("F.Cu", 0.3), ("B.Cu", 0.5))
    tasks = (Task("X", ("J1", "1"), ("Q1", "1"), a), Task("Y", ("J1", "2"), ("Q1", "2"), b))
    first = plan_calls(Selection("p", "connections", tasks=tasks, layers=("F.Cu", "B.Cu")), {}, 0.15, set())
    again = plan_calls(Selection("p", "connections", tasks=tasks[::-1], layers=("F.Cu", "B.Cu")), {}, 0.15, set())
    assert [c.tasks[0].widths for c in first] == [c.tasks[0].widths for c in again]


def test_the_rest_routes_wide_clearances_by_name_then_everything_else():
    calls = plan_calls(Selection("signals", "rest", nets=("A", "RF", "B"), rest=True), {"RF": 0.2}, 0.15, {"GND"})
    assert [(c.kind, c.nets) for c in calls[:1]] == [("nets", ("RF",))]
    assert calls[1].kind == "rest" and set(calls[1].excluded) == {"GND", "RF"}


def test_pairs_pours_and_buses_each_route_in_their_own_calls():
    sel = Selection("p", "nets", nets=("S",), pour_nets=("VB", "GND"), layers=("F.Cu",))
    assert [c.kind for c in plan_calls(sel, {}, 0.15, set())] == ["pour", "pour", "nets"]
    sel = Selection("b", "buses", buses=(("D0", "D1"), ("A0", "A1")))
    assert [c.nets for c in plan_calls(sel, {}, 0.15, set())] == [("D0", "D1"), ("A0", "A1")]


def test_the_tasks_of_a_pour_net_route_in_its_pour_call_not_a_task_call():
    """A task set's pour nets route alone with their pour as a zone (D15, ruling S5): their tasks ride the pour call,
    at the widest width any of them asks, and no task call routes them again. A current_paths phase has no such tasks:
    it leaves a pour net to its pour (ruling S13)."""
    tasks = (Task("VB", ("J1", "1"), ("Q1", "1"), W3, 1.0), Task("VB", ("J1", "1"), ("U1", "1"), W5, 4.0),
             Task("SW", ("Q1", "2"), ("L1", "1"), W3, 1.0))
    sel = Selection("p", "connections", tasks=tasks, pour_nets=("VB",), layers=("F.Cu", "B.Cu"))
    calls = plan_calls(sel, {}, 0.15, set())
    assert [(c.kind, c.nets, len(c.tasks)) for c in calls] == [("pour", ("VB",), 2), ("tasks", (), 1)]
    assert calls[0].width == 0.5 and calls[1].tasks[0].net == "SW"


def test_a_pour_call_of_whole_nets_keeps_the_phase_width():
    sel = Selection("p", "nets", pour_nets=("VB",), width=0.8, layers=("F.Cu",))
    assert plan_calls(sel, {}, 0.15, set()) == [Call("pour", ("VB",), width=0.8)]


def test_the_connections_file_is_structured(tmp_path):
    p = write_connections((Task("!RST", ("U1", "3"), ("J1", "1"), W5, None),), tmp_path / "c.json", ("F.Cu", "B.Cu"))
    assert json.loads(p.read_text()) == [{"net": "!RST", "from": {"ref": "U1", "pad": "3"}, "to": {"ref": "J1", "pad": "1"},
                                          "widths": {"F.Cu": 0.5, "B.Cu": 0.5}}]


def test_a_task_whose_widths_miss_a_routed_layer_is_not_written(tmp_path):
    with pytest.raises(ValueError) as e:
        write_connections((Task("VB", ("J1", "1"), ("Q1", "1"), (("F.Cu", 0.5),), None),), tmp_path / "c.json",
                          ("F.Cu", "B.Cu"))
    assert e.value.args[0] == "layer_width_missing" and e.value.args[1]["net"] == "VB"
    assert not (tmp_path / "c.json").exists()


def test_a_task_with_a_width_on_a_layer_not_routed_is_not_written(tmp_path):
    with pytest.raises(ValueError) as e:
        write_connections((Task("VB", ("J1", "1"), ("Q1", "1"), W5, None),), tmp_path / "c.json", ("F.Cu",))
    assert e.value.args[0] == "layer_not_routed"
    assert not (tmp_path / "c.json").exists()


def test_the_routers_refusals_are_read_from_its_records():
    end = {"ref": "J1", "pad": "1"}
    recs = [dict(net="VB", to=end, status="refused", reason="pad_not_on_net", joined=False, **{"from": end}),
            dict(net="VB", to=end, status="routed", reason=None, joined=True, **{"from": end})]
    assert refused_records(recs) == [{"net": "VB", "from": end, "to": end, "reason": "pad_not_on_net"}]


def test_a_call_with_connections_names_no_nets_and_carries_the_phase_flags(tmp_path):
    with bind(Settings(route_router_args=("--via-cost", "50"))):
        cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu"], tmp_path / "s.json",
                             connections=tmp_path / "c.json", neckdown=False, extra_args=("--bus-detection-radius", "3"))
    assert "--nets" not in cmd and cmd[cmd.index("--connections") + 1] == str(tmp_path / "c.json")
    assert "--no-power-tap-neckdown" in cmd
    assert cmd.index("--via-cost") < cmd.index("--bus-detection-radius") < cmd.index("--json-out")


def test_neck_down_stays_the_routers_default_unless_a_phase_turns_it_off(tmp_path):
    with bind(Settings()):
        cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu"], tmp_path / "s.json", nets=["A"])
    assert "--no-power-tap-neckdown" not in cmd and "--connections" not in cmd and "--bus-nets" not in cmd


def test_a_bus_call_states_its_nets_and_an_active_low_net_is_escaped(tmp_path):
    with bind(Settings()):
        cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu"], tmp_path / "s.json",
                             nets=["!RST", "D1"], bus_nets=["!RST", "D1"])
    i = cmd.index("--bus-nets")
    assert cmd[i + 1:i + 3] == ["\\!RST", "D1"] and cmd[cmd.index("--nets") + 1] == "\\!RST"


def test_a_power_width_names_an_active_low_net_as_it_is(tmp_path):
    """KRT matches --power-nets with plain fnmatch (net_queries.py identify_power_nets), which knows no '\\!' escape."""
    with bind(Settings()):
        cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu"], tmp_path / "s.json",
                             nets=["!EN"], widths={"!EN": 0.4})
    assert cmd[cmd.index("--power-nets") + 1] == "!EN" and cmd[cmd.index("--power-nets-widths") + 1] == "0.4"


def test_clearance_groups_route_the_widest_clearance_first():
    assert clearance_groups({"RF": 0.2, "W": 0.3, "EQ": 0.127}, 0.127, {"RF", "W", "EQ", "S"}) == [(0.3, ["W"]), (0.2, ["RF"])]


def test_a_router_without_a_capability_list_lacks_every_requirement(tmp_path):
    import sys
    assert router_capable(sys.executable, tmp_path) == list(REQUIRES)


def _krt():
    d = os.environ.get("KRT_DIR")
    if not d or not (Path(d) / "krt_capabilities.py").exists():
        pytest.skip("KRT_DIR names no router with krt_capabilities.py")
    py = Path(d) / ".venv" / "bin" / "python"
    return (str(py) if py.exists() else "python3"), d


def test_every_flag_a_phase_call_passes_is_one_the_router_parses(tmp_path):
    """The names must be KRT's argparse names exactly; a flag the router lacks is one router_capable reports."""
    rpy, d = _krt()
    caps = json.loads(subprocess.run([rpy, str(Path(d) / "krt_capabilities.py")], capture_output=True, text=True,
                                     cwd=d, timeout=60, check=True).stdout)
    known = set(caps["flags"]["route.py"])
    lacking = {r.split(":", 1)[1] for r in router_capable(rpy, d)}
    with bind(Settings()):
        cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu"], tmp_path / "s.json", iterations=5,
                             probe=5, nets=["A", "B"], widths={"A": 0.5}, clearances=tmp_path / "c.json",
                             bus_nets=["A", "B"], neckdown=False)
        cmd += router_command("py", "route.py", "in", "out", set(), ["F.Cu"], tmp_path / "s.json",
                              connections=tmp_path / "k.json")
    flags = {a for a in cmd if a.startswith("--")}
    assert flags - known <= lacking and lacking <= set(r.split(":", 1)[1] for r in REQUIRES)


@pytest.mark.parametrize("given", [dict(nets=["A"]), dict(widths={"A": 0.5}), dict(excluded={"GND"})])
def test_a_connections_call_with_nets_widths_or_exclusions_is_refused(tmp_path, given):
    """KRT exits 2 on --nets or --power-nets beside --connections (docs/connections.md); exclusions would be dropped."""
    excluded = given.pop("excluded", set())
    with bind(Settings()), pytest.raises(ValueError) as e:
        router_command("py", "route.py", "in", "out", excluded, ["F.Cu"], tmp_path / "s.json",
                       connections=tmp_path / "c.json", **given)
    assert e.value.args[0] == "connections_with"


def test_task_clearances_group_as_whole_nets_do():
    """Rounded to 6 places, and a clearance within 1e-9 of the base is the base (clearance_groups)."""
    tasks = (Task("A", ("J1", "1"), ("Q1", "1"), W3), Task("B", ("J1", "2"), ("Q1", "2"), W3),
             Task("C", ("J1", "3"), ("Q1", "3"), W3), Task("D", ("J1", "4"), ("Q1", "4"), W3))
    sel = Selection("p", "connections", tasks=tasks, layers=("F.Cu", "B.Cu"))
    calls = plan_calls(sel, {"A": 0.2 + 1e-12, "B": 0.2, "C": 0.15 + 1e-12}, 0.15, set())
    assert [(c.clearance, [t.net for t in c.tasks]) for c in calls] == [(0.2, ["A", "B"]), (0.15, ["C", "D"])]


def test_a_net_name_with_glob_characters_is_written_to_take_that_net_alone(tmp_path):
    import fnmatch
    from placemat.kicad.phase_select import net_matches
    nets = ["D[0]", "D0", "D*", "DX", "D?", "!D[0]", "!D0"]
    for name in nets:
        assert [n for n in nets if net_matches(n, router_net_pattern(name, "include").replace("\\!", "!", 1))] == [name]
        assert [n for n in nets if fnmatch.fnmatch(n, router_net_pattern(name, "power"))] == [name]
    with bind(Settings()):
        cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu"], tmp_path / "s.json",
                             nets=["D[0]"], widths={"D[0]": 0.4}, bus_nets=["D[0]", "D0"])
    assert cmd[cmd.index("--nets") + 1] == "D[[]0]" and cmd[cmd.index("--power-nets") + 1] == "D[[]0]"
    assert cmd[cmd.index("--bus-nets") + 1:cmd.index("--bus-nets") + 3] == ["D[[]0]", "D0"]
    with bind(Settings()):
        cmd = router_command("py", "route.py", "in", "out", {"D[0]"}, ["F.Cu"], tmp_path / "s.json")
    assert cmd[cmd.index("--nets") + 1:cmd.index("--nets") + 3] == ["*", "!D[[]0]"]


_KRT_READS = """
import contextlib, io, json, sys
from types import SimpleNamespace as N
import net_queries as q
names, nets_args, excl_args, power_args = json.load(sys.stdin)
pcb = N(nets={i + 1: N(name=n) for i, n in enumerate(names)}, pads_by_net={})
with contextlib.redirect_stdout(io.StringIO()):
    taken = [sorted(q.expand_net_patterns(pcb, [a])) for a in nets_args]
    excluded = [sorted(q.expand_net_patterns(pcb, ["*", a])) for a in excl_args]
    power = [sorted(pcb.nets[i].name for i in q.identify_power_nets(pcb, [a], [0.5])) for a in power_args]
print(json.dumps([taken, excluded, power]))
"""


def test_the_router_reads_each_written_name_as_that_net_alone():
    """KRT's own expand_net_patterns (--nets, and the '!NET' of a `*` call) and identify_power_nets (--power-nets) on
    D[0] beside D0. A name with no '/' also takes a sheet-qualified net of the same last part (the leaf rule)."""
    rpy, d = _krt()
    names = ["D[0]", "D0", "D*", "DX", "!RST", "RST", "/Sub/D[0]"]
    plain = names[:-1]
    got = subprocess.run([rpy, "-c", _KRT_READS], cwd=str(Path(d) / "py_router"), capture_output=True, text=True,
                         timeout=60, check=True, input=json.dumps([names] + [[router_net_pattern(n, f) for n in plain]
                                                                  for f in ("include", "exclude", "power")]))
    taken, excluded, power = json.loads(got.stdout)
    leaf = {"D[0]": ["/Sub/D[0]", "D[0]"]}
    assert taken == [leaf.get(n, [n]) for n in plain]
    assert power == [[n] for n in plain]
    assert excluded[:2] == [sorted(set(names) - {"D[0]", "/Sub/D[0]"}), sorted(set(names) - {"D0"})]


def test_current_buses_preserve_each_bus_call_and_its_task_widths():
    tasks = (Task("A", ("J1", "1"), ("Q1", "1"), W3, 1.0), Task("B", ("J1", "2"), ("Q1", "2"), W5, 4.0))
    calls = plan_calls(Selection("p", "buses", buses=(("A",), ("B",)), tasks=tasks, layers=("F.Cu", "B.Cu")), {}, 0.15, set())
    assert [c.kind for c in calls] == ["bus_tasks", "bus_tasks"]
    assert [c.nets for c in calls] == [("A",), ("B",)] and [c.tasks for c in calls] == [(tasks[0],), (tasks[1],)]
    cmd = router_command("py", "route.py", "in", "out", set(), ["F.Cu", "B.Cu"], "s.json", connections=Path("tasks.json"), bus_nets=["A", "B"])
    assert cmd[cmd.index("--connections") + 1] == "tasks.json" and cmd[cmd.index("--bus-nets") + 1:cmd.index("--bus-nets") + 3] == ["A", "B"]
