"""`[route] pair_layers`: a differential pair the table names is routed on the layers it gives, every other pair on the
route's own layers. The pair router takes one layer list per call, so the pairs are routed in one call per distinct
list, the named ones first; each call's copper is fixed for the next."""
import json
import shutil
from pathlib import Path

import pytest

from placemat.findings import Finding, FindingCause as C
from placemat.kicad.route import pair_layer_groups, resolve_pair_layers
from placemat.settings import SettingsError, load
from tests.conftest import needs_kicad

STACK = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]


# ---------------------------------------------------------------- the setting

def test_the_table_loads_inline_and_as_its_own_table(tmp_path):
    (tmp_path / "placemat.toml").write_text('[route]\npair_layers = {"A_P/A_N" = ["In2.Cu", "B.Cu"]}\n')
    assert load(tmp_path).route_pair_layers == {"A_P/A_N": ["In2.Cu", "B.Cu"]}
    (tmp_path / "placemat.toml").write_text('[route.pair_layers]\nUSB = ["B.Cu"]\n')
    assert load(tmp_path).route_pair_layers == {"USB": ["B.Cu"]}
    (tmp_path / "placemat.toml").write_text("[route]\nquick = false\n")
    assert load(tmp_path).route_pair_layers == {}


@pytest.mark.parametrize("layers", [['"In2.cu"'], ['"Top"'], ['"In31.Cu"'], ['"F.Cu"', '"Edge.Cuts"']])
def test_an_unknown_layer_name_is_refused_when_the_settings_load(tmp_path, layers):
    (tmp_path / "placemat.toml").write_text('[route]\npair_layers = {"A_P/A_N" = [%s]}\n' % ", ".join(layers))
    with pytest.raises(SettingsError, match=r"route\.pair_layers.*A_P/A_N.*not a copper layer"):
        load(tmp_path)


@pytest.mark.parametrize("value", ['"In2.Cu"', "[]", "[1]"])
def test_an_entry_that_is_not_a_list_of_layer_names_is_refused(tmp_path, value):
    (tmp_path / "placemat.toml").write_text('[route]\npair_layers = {"A_P/A_N" = %s}\n' % value)
    with pytest.raises(SettingsError, match=r"route\.pair_layers.*A_P/A_N"):
        load(tmp_path)


# ---------------------------------------------------------------- which pair an entry names

PAIRS = [("A_P", "A_N"), ("B_P", "B_N"), ("C_P", "C_N")]
CLASSES = {"A_P": "Fast", "A_N": "Fast", "B_P": "Slow", "B_N": "Slow", "C_P": "Slow", "C_N": "Slow"}


def test_a_key_names_a_pair_by_its_two_nets_in_either_order_or_by_its_net_class():
    got, refused = resolve_pair_layers({"A_N/A_P": ["B.Cu"], "Slow": ["In2.Cu"]}, PAIRS, CLASSES, STACK)
    assert refused == []
    assert got == {("A_P", "A_N"): ["B.Cu"], ("B_P", "B_N"): ["In2.Cu"], ("C_P", "C_N"): ["In2.Cu"]}


def test_a_pairs_own_nets_win_over_its_class():
    got, _ = resolve_pair_layers({"Slow": ["In2.Cu"], "C_P/C_N": ["B.Cu"]}, PAIRS, CLASSES, STACK)
    assert got == {("B_P", "B_N"): ["In2.Cu"], ("C_P", "C_N"): ["B.Cu"]}


def test_the_layers_go_in_the_boards_stack_order():
    got, _ = resolve_pair_layers({"A_P/A_N": ["B.Cu", "In2.Cu", "B.Cu"]}, PAIRS, CLASSES, STACK)
    assert got == {("A_P", "A_N"): ["In2.Cu", "B.Cu"]}


def test_a_key_that_names_no_pair_or_a_layer_the_board_lacks_is_refused_as_facts():
    got, refused = resolve_pair_layers({"X_P/X_N": ["B.Cu"], "Fast": ["In4.Cu", "B.Cu"], "B_P/B_N": ["In1.Cu"]},
                                       PAIRS, CLASSES, STACK)
    assert got == {("B_P", "B_N"): ["In1.Cu"]}
    assert refused == [
        {"key": "Fast", "variant": "layer_missing", "layers": ["In4.Cu", "B.Cu"], "missing": ["In4.Cu"], "board_layers": STACK},
        {"key": "X_P/X_N", "variant": "no_pair", "layers": ["B.Cu"], "missing": [], "board_layers": STACK}]


def test_a_refused_entry_is_a_setup_finding():
    f = Finding(C.SETUP_PAIR_LAYERS, {"key": "Fast", "variant": "layer_missing", "layers": ["In4.Cu", "B.Cu"],
                                      "missing": ["In4.Cu"], "board_layers": STACK})
    assert f.severity == "warning" and "In4.Cu" in str(f) and "Fast" in str(f)
    g = Finding(C.SETUP_PAIR_LAYERS, {"key": "X_P/X_N", "variant": "no_pair", "layers": ["B.Cu"], "missing": [],
                                      "board_layers": STACK})
    assert "X_P/X_N" in str(g)


def test_the_route_report_carries_the_refusals_as_findings(tmp_path):
    from placemat.kicad.route import RouteReport
    rep = RouteReport(True, 1.0, 1.0, 0, 0, {}, [], [], STACK, 0.0, "v", {}, tmp_path, tmp_path, tmp_path)
    rep.pair_layers_refused = [{"key": "X_P/X_N", "variant": "no_pair", "layers": ["B.Cu"], "missing": [],
                                "board_layers": STACK}]
    rep.pair_layers = {"A_P/A_N": ["B.Cu"]}
    found = rep.findings()
    assert [f.cause for f in found] == [C.SETUP_PAIR_LAYERS] and found[0].facts["key"] == "X_P/X_N"
    d = rep.as_dict()
    assert d["pair_layers"] == {"A_P/A_N": ["B.Cu"]} and d["pair_layers_refused"][0]["variant"] == "no_pair"


# ---------------------------------------------------------------- one call per layer list

def test_the_pairs_are_grouped_by_their_layers_the_named_ones_first():
    groups = pair_layer_groups(PAIRS, ["F.Cu", "B.Cu"], {("C_P", "C_N"): ["In2.Cu", "B.Cu"]})
    assert groups == [(["In2.Cu", "B.Cu"], [("C_P", "C_N")]), (["F.Cu", "B.Cu"], [("A_P", "A_N"), ("B_P", "B_N")])]
    # an entry that gives the route's own list routes with the rest
    assert pair_layer_groups(PAIRS, ["F.Cu", "B.Cu"], {("C_P", "C_N"): ["F.Cu", "B.Cu"]}) == [(["F.Cu", "B.Cu"], PAIRS)]
    assert pair_layer_groups(PAIRS, ["F.Cu", "B.Cu"], {}) == [(["F.Cu", "B.Cu"], PAIRS)]


NETS = ("A_P", "A_N", "B_P", "B_N")


def _router(tmp_path) -> Path:
    router = tmp_path / "router"
    (router / "py_router").mkdir(parents=True)
    (router / "py_router/route_diff.py").write_text("")
    return router


def _board(tmp_path) -> Path:
    """A four-layer board with two parts, each with a pad per net of two pairs and one for a single net (the main pass
    has a net to route), and a project giving each pair a pair class."""
    pads = list(zip(NETS + ("SIG",), (-1.2, -0.4, 1.2, 2.0, 4.0)))

    def part(ref, x, y):
        body = "".join('\t\t(pad "%d" smd rect (at %g 0) (size 0.4 1.2) (layers "F.Cu" "F.Mask") (net "%s"))\n'
                       % (i + 1, at, net) for i, (net, at) in enumerate(pads))
        return ('\t(footprint "t:conn" (layer "F.Cu") (at %g %g)\n\t\t(property "Reference" "%s" (at 0 -2 0) '
                '(layer "F.SilkS"))\n%s\t)\n' % (x, y, ref, body))
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
                   '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(4 "In1.Cu" signal)\n\t\t(6 "In2.Cu" signal)\n\t\t(2 "B.Cu" signal)\n'
                   '\t\t(25 "Edge.Cuts" user)\n\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n'
                   + "".join('\t(net %d "%s")\n' % (i + 1, n) for i, (n, _) in enumerate(pads))
                   + part("J1", 110, 108) + part("J2", 130, 120)
                   + '\t(gr_rect (start 100 100) (end 140 128) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))\n)\n')
    pro = {"meta": {"filename": "board.kicad_pro", "version": 3},
           "net_settings": {"classes": [{"name": "Default", "clearance": 0.15, "track_width": 0.15},
                                        {"name": "Fast", "clearance": 0.15, "track_width": 0.15,
                                         "diff_pair_gap": 0.2, "diff_pair_width": 0.2},
                                        {"name": "Slow", "clearance": 0.15, "track_width": 0.15,
                                         "diff_pair_gap": 0.2, "diff_pair_width": 0.2}],
                            "netclass_assignments": {"A_P": ["Fast"], "A_N": ["Fast"], "B_P": ["Slow"], "B_N": ["Slow"]}}}
    pcb.with_suffix(".kicad_pro").write_text(json.dumps(pro))
    return pcb


@needs_kicad
def test_two_pairs_one_named_route_in_two_calls_each_on_its_own_layers(tmp_path, monkeypatch):
    """The stage's router commands, with a stand-in router that copies its input and reports its pairs routed."""
    import types
    import placemat.kicad.route as route_mod
    from placemat.settings import Settings, bind
    calls = []

    def stand_in(cmd, stdout=None, **kw):
        calls.append(list(cmd))
        i = cmd.index("--nets")
        shutil.copy(cmd[i - 2], cmd[i - 1])
        names = cmd[i + 1:cmd.index("--layers")]
        stdout.write("JSON_SUMMARY: " + json.dumps({"routed_diff_pairs": names, "failed_diff_pairs": [], "partial_diff_pairs": [],
                                                    "single_ended_diff_pairs": [], "pair_reports": [
                                                        {"pair": n, "p_net": n + "_P", "n_net": n + "_N"} for n in names]}) + "\n")
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(route_mod.subprocess, "run", stand_in)
    pcb = _board(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    pairs = [("A_P", "A_N"), ("B_P", "B_N")]
    with bind(Settings(route_pair_router_args=("--max-turn-angle", "90"))):
        board, out = route_mod.route_pairs("py", _router(tmp_path), pcb, work, pairs, ["F.Cu", "B.Cu"], Settings(), None, None, 60, {},
                                           pair_layers={("B_P", "B_N"): ["In2.Cu", "B.Cu"]})

    def layers(cmd):
        return cmd[cmd.index("--layers") + 1:cmd.index("--escalation")]

    def nets(cmd):
        return cmd[cmd.index("--nets") + 1:cmd.index("--layers")]
    assert [layers(c) for c in calls] == [["In2.Cu", "B.Cu"], ["F.Cu", "B.Cu"]]
    assert len(nets(calls[0])) == 1 and len(nets(calls[1])) == 1 and nets(calls[0]) != nets(calls[1])
    # the second call routes on the first one's board, and both keep the input copper and take the pair router's own args
    i = calls[1].index("--nets")
    assert calls[1][i - 2] == calls[0][i - 1]
    assert all("--keep-input-copper" in c and c[-2:] == ["--max-turn-angle", "90"] for c in calls)
    assert board == work / "pairs.kicad_pcb" and board.exists()
    assert out.coupled == ["A_P/A_N", "B_P/B_N"] and out.routed_nets == set(NETS)
    assert (work / "pairs.log").exists() and (work / "pairs_1.log").exists()


@needs_kicad
def test_with_no_entry_the_pairs_are_one_call(tmp_path, monkeypatch):
    import types
    import placemat.kicad.route as route_mod
    from placemat.settings import Settings
    calls = []

    def stand_in(cmd, stdout=None, **kw):
        calls.append(list(cmd))
        i = cmd.index("--nets")
        shutil.copy(cmd[i - 2], cmd[i - 1])
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(route_mod.subprocess, "run", stand_in)
    pcb = _board(tmp_path)
    (tmp_path / "work").mkdir()
    route_mod.route_pairs("py", _router(tmp_path), pcb, tmp_path / "work", [("A_P", "A_N"), ("B_P", "B_N")], ["F.Cu", "B.Cu"],
                          Settings(), None, None, 60, {})
    assert len(calls) == 1
    assert calls[0][calls[0].index("--layers") + 1:calls[0].index("--escalation")] == ["F.Cu", "B.Cu"]


def test_the_route_command_prints_a_refused_entry_and_json_carries_it(tmp_path, monkeypatch, capsys):
    from placemat import cli
    import placemat.kicad.route as route_mod
    from placemat.kicad.route import RouteReport
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("")
    report = RouteReport(True, 1.0, 1.0, 1, 0, {}, [], [], STACK, 1.0, "v", {}, Path("r.kicad_pcb"), Path("r.log"), Path("."))
    report.pair_layers_refused = [{"key": "X_P/X_N", "variant": "no_pair", "layers": ["B.Cu"], "missing": [],
                                   "board_layers": STACK}]
    monkeypatch.setattr(route_mod, "route_board", lambda *a, **kw: report)
    assert cli.main(["route", str(pcb)]) == 0
    assert "route.pair_layers X_P/X_N: no differential pair" in capsys.readouterr().out
    assert cli.main(["route", str(pcb), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [d["cause"] for d in doc["finding_details"]] == ["setup.pair_layers"]
    assert doc["pair_layers_refused"][0]["key"] == "X_P/X_N"
