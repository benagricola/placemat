"""route --phase NAME routes up to and including NAME; --only routes just it on the board as it is; each phase is
said with its closure."""
from placemat.cli import parser
from placemat.kicad.route import phase_lines


def test_the_route_command_takes_phase_and_only():
    a = parser().parse_args(["route", "b.kicad_pcb", "--phase", "legs", "--only"])
    assert a.phase == "legs" and a.only is True


def test_only_without_a_phase_is_refused(capsys):
    from placemat.cli import main
    assert main(["route", "b.kicad_pcb", "--only"]) == 2
    assert "--only routes the phase --phase names" in capsys.readouterr().out


def test_each_phase_is_one_line_with_its_closure_and_what_is_open():
    lines = phase_lines([
        {"name": "legs", "selector": "current_paths", "asked": 4, "joined": 3, "closure_clean": 0.75, "seconds": 12.0,
         "reused": False, "open": [{"net": "VB", "from": {"ref": "J1", "pad": "2"}, "to": {"ref": "Q1", "pad": "1"}}]},
        {"name": "signals", "selector": "rest", "asked": 40, "joined": 40, "closure_clean": 1.0, "seconds": 80.0,
         "reused": True, "open": []}], ["legs"])
    assert lines[0] == "phase legs (current_paths): 3 of 4 joined clean (75.0%), 12 s; open: VB J1.2-Q1.1"
    assert lines[1] == "phase signals (rest): 40 of 40 joined clean (100.0%), 80 s, reused"
    assert lines[2] == "earlier phases with no copper on this board: legs"


def test_a_net_phase_names_its_open_connections_a_loose_end_by_place_and_a_violated_net():
    (line,) = phase_lines([
        {"name": "fb", "selector": "nets", "asked": 3, "joined": 1, "closure_clean": 0.3333, "seconds": 2.0,
         "reused": False, "open": [{"net": "FB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": None, "pad": None,
                                                                                           "at": [10.0, 5.5]}},
                                   {"net": "SW", "violated": True}]}])
    assert line.endswith("; open: FB J1.1-10.00,5.50, SW has a DRC error")


def test_an_open_connection_says_what_the_router_reported_and_the_final_closure():
    (line,) = phase_lines([
        {"name": "legs", "selector": "current_paths", "asked": 1, "joined": 0, "closure_clean": 0.0,
         "final_closure_clean": 1.0, "seconds": 3.0, "reused": False,
         "open": [{"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "J2", "pad": "1"}, "outcome": "failed",
                   "evidence": {"diagnosis": "unknown", "blocked_by": [
                       {"ref": "U1", "net": "N1"}, {"ref": "U1", "net": "N2"}, {"ref": None, "net": "GND"}]}}]}])
    assert line == ("phase legs (current_paths): 0 of 1 joined clean (0.0%), 3 s, final 100.0%; "
                    "open: VB J1.1-J2.1 failed against U1/GND copper")


def test_a_net_with_a_drc_error_is_said_once_and_a_diagnosis_is_said_when_krt_gave_one():
    sw = {"net": "SW", "from": {"ref": "L1", "pad": "1"}, "to": {"ref": "U1", "pad": "1"}, "violated": True}
    fb = {"net": "FB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "U1", "pad": "2"}, "outcome": "failed",
          "evidence": {"diagnosis": "boxed_in_static", "blocked_by": []}}
    (line,) = phase_lines([{"name": "n", "selector": "nets", "asked": 3, "joined": 0, "closure_clean": 0.0,
                            "seconds": 1.0, "open": [sw, dict(sw, to={"ref": "C1", "pad": "1"}), fb]}])
    assert line.endswith("; open: SW has a DRC error, FB J1.1-U1.2 failed boxed_in_static")


def test_a_join_under_its_width_is_said_with_its_narrowest_copper():
    vb = {"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "J2", "pad": "1"}, "outcome": "joined_narrow",
          "under": {"F.Cu": 0.2}}
    (line,) = phase_lines([{"name": "legs", "selector": "current_paths", "asked": 1, "joined": 0, "closure_clean": 0.0,
                            "seconds": 1.0, "open": [vb]}])
    assert line.endswith("; open: VB J1.1-J2.1 under F.Cu 0.2")


def test_missing_width_policy_cli_is_structured_refusal(tmp_path, monkeypatch, capsys):
    import json
    from placemat import channel, runner, settings
    from placemat.cli import main
    from placemat.kicad import route
    board = tmp_path / 'board.kicad_pcb'
    board.write_text('unused: capability refuses before route')
    monkeypatch.setattr(runner, 'missing_rules', lambda _: [])
    monkeypatch.setattr(route, 'plane_nets_of', lambda _: [])
    monkeypatch.setattr(settings, 'load', lambda *a, **k: settings.Settings())
    monkeypatch.setattr(channel, 'reporter', lambda *a: None)
    monkeypatch.setattr(channel, 'error', lambda *a, **k: None)
    def unavailable(*args, **kwargs):
        raise route.RouteRefused('width_policy_unavailable', router='old-krt',
                                 script='old-krt/py_router/nominal_width_policy.py')
    monkeypatch.setattr(route, 'route_board', unavailable)
    assert main(['route', str(board), '--json']) == 2
    record = json.loads(capsys.readouterr().out)
    assert record == {'code': 'width_policy_unavailable', 'router': 'old-krt',
                      'script': 'old-krt/py_router/nominal_width_policy.py'}


def test_a_failed_width_query_reads_as_its_failure_and_log():
    from placemat.kicad.route import refused_text
    text = refused_text('width_policy_failed', {'router': 'krt', 'failure': 'timeout', 'seconds': 60.0,
                                                'log': 'work/width_policy.log'})
    assert text == "route: the router's width query gave no widths: timeout; its output is in work/width_policy.log"


def test_an_unmeasured_join_reads_width_not_measured():
    from placemat.kicad.route import phase_lines
    p = {"name": "legs", "selector": "connections", "joined": 0, "asked": 1, "closure_clean": 0.0, "seconds": 1.0,
         "open": [{"net": "SW", "from": {"ref": "Q1", "pad": "2"}, "to": {"ref": "L1", "pad": "1"},
                   "width_unknown": True}]}
    assert any("SW Q1.2-L1.1 width not measured" in line for line in phase_lines([p]))


def test_a_phase_names_the_connections_it_left_to_their_pours_and_the_ones_the_pour_missed():
    """Ruling S13: a current_paths phase's connections on a pour net are asked of the pour; the line counts the ones it
    joins per net and names each one it does not join."""
    gnd = {"net": "GND", "from": {"ref": "J1", "pad": "2"}, "to": {"ref": "U1", "pad": "3"}}
    missed = dict(gnd, to={"ref": "U2", "pad": "1"})
    (line,) = phase_lines([{"name": "current", "selector": "current_paths", "asked": 4, "joined": 3,
                            "closure_clean": 0.75, "seconds": 1.0,
                            "open": [dict(missed, widths=None, pour_served=True, outcome=None, evidence=None)],
                            "pour_served": [dict(gnd, joined=True), dict(gnd, to={"ref": "U3", "pad": "1"}, joined=True),
                                            dict(missed, joined=False), dict(gnd, net="VB", joined=True)]}])
    assert line == ("phase current (current_paths): 3 of 4 joined clean (75.0%), 1 s; left to their pours: "
                    "GND 2 connections, VB 1 connection; not reached by the pour: GND J1.2-U2.1")


def test_a_connection_the_pour_joins_under_its_current_width_is_named_under_not_unreached():
    gnd = {"net": "GND", "from": {"ref": "J1", "pad": "2"}, "to": {"ref": "U1", "pad": "3"}}
    thin = dict(gnd, to={"ref": "U2", "pad": "1"})
    (line,) = phase_lines([{"name": "current", "selector": "current_paths", "asked": 2, "joined": 1,
                            "closure_clean": 0.5, "seconds": 1.0,
                            "open": [dict(thin, widths={"F.Cu": 1.0}, pour_served=True, under={"F.Cu": 0.2},
                                          outcome=None, evidence=None)],
                            "pour_served": [dict(gnd, joined=True), dict(thin, joined=True, under={"F.Cu": 0.2})]}])
    assert line == ("phase current (current_paths): 1 of 2 joined clean (50.0%), 1 s; open: GND J1.2-U2.1 under "
                    "F.Cu 0.2; left to their pours: GND 1 connection")


def test_a_pour_net_a_later_phase_routes_is_said_so():
    gnd = {"net": "GND", "from": {"ref": "J1", "pad": "2"}, "to": {"ref": "U1", "pad": "3"}, "joined": True}
    phases = [{"name": "current", "selector": "current_paths", "asked": 1, "joined": 1, "closure_clean": 1.0,
               "seconds": 1.0, "open": [], "pour_served": [gnd]},
              {"name": "gnd", "selector": "nets", "asked": 1, "joined": 1, "closure_clean": 1.0, "seconds": 1.0,
               "open": []}]
    assert phase_lines(phases, (), {"GND": "gnd"})[0].endswith("; left to their pours: GND 1 connection routed by phase gnd")
    assert phase_lines(phases, (), {"GND": "current"})[0].endswith("; left to their pours: GND 1 connection")


def test_a_phase_record_carries_each_connection_left_to_its_pour_and_whether_it_joined():
    from placemat.kicad.phase_run import phase_record
    a = {"net": "GND", "from": {"ref": "J1", "pad": "2"}, "to": {"ref": "U1", "pad": "3"}, "widths": None,
         "pour_served": True}
    b = dict(a, to={"ref": "U2", "pad": "1"})
    phase = type("P", (), {"record": lambda self: {"name": "current"}, "max_uncoupled_mm": None})()
    c = dict(a, to={"ref": "U3", "pad": "1"})
    judged = [{"joined": True, "violated": False, "under": {}}, {"joined": False, "violated": False, "under": {}},
              {"joined": True, "violated": False, "under": {"F.Cu": 0.2}}]
    rec = phase_record(phase, 0, None, [a, b, c], judged, 1.0, 0)
    assert rec["pour_served"] == [{"net": "GND", "from": a["from"], "to": a["to"], "joined": True},
                                  {"net": "GND", "from": b["from"], "to": b["to"], "joined": False},
                                  {"net": "GND", "from": c["from"], "to": c["to"], "joined": True,
                                   "under": {"F.Cu": 0.2}}]
    assert (rec["asked"], rec["joined"]) == (3, 1) and [o["to"] for o in rec["open"]] == [b["to"], c["to"]]
    assert phase_record(phase, 0, None, [], [], 1.0, 0)["pour_served"] == []


def test_a_phase_with_only_connections_left_to_pours_is_not_named_as_having_no_copper():
    from types import SimpleNamespace as N
    from placemat.kicad.phase_select import Selection, Task
    from placemat.kicad.route import without_copper
    t = Task("GND", ("J1", "2"), ("U1", "3"), (("F.Cu", 1.0),), 2.0)
    sels = [Selection("current", "current_paths", pour_served=(t,)), Selection("fb", "nets", nets=("FB",))]
    assert without_copper(sels, N(copper=())) == ["fb"]
