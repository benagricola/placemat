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
                                 receipt='width_policy.json', reason='missing nominal helper')
    monkeypatch.setattr(route, 'route_board', unavailable)
    assert main(['route', str(board), '--json']) == 2
    record = json.loads(capsys.readouterr().out)
    assert record == {'code': 'width_policy_unavailable', 'router': 'old-krt',
                      'receipt': 'width_policy.json', 'reason': 'missing nominal helper'}
