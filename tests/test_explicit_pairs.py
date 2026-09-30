"""A `route.diff_pairs` entry "NET_A/NET_B" names a pair outright: the first
net is P, the second N. The router pairs nets only by their suffix, so the
route step renames the two in its own copy to a suffix pair, passes that
name to the pair router, and renames them back in the routed copy."""
import json
import shutil
import subprocess

import pytest

from placemat.pairs import explicit_pairs, pair_aliases, pairs_of
from tests.conftest import needs_kicad


# ---------------------------------------------------------------- naming a pair

def test_an_entry_with_one_slash_names_a_pair():
    assert explicit_pairs(("*", "LEAD_A/LEAD_B")) == [("LEAD_A", "LEAD_B")]
    # a glob, or a hierarchical base with a leading slash, is still a pattern
    assert explicit_pairs(("/usb*", "/sheet/D", "LEAD_*/X", "/D_CK")) == []


def test_pairs_of_includes_an_explicit_pair_whose_two_nets_are_present():
    nets = ["LEAD_A", "LEAD_B", "USB_P", "USB_N", "SIG"]
    assert pairs_of(nets, ("LEAD_A/LEAD_B",)) == {"LEAD_A": "LEAD_B", "LEAD_B": "LEAD_A"}
    assert pairs_of(nets, ("*", "LEAD_A/LEAD_B")) == {"LEAD_A": "LEAD_B", "LEAD_B": "LEAD_A",
                                                      "USB_P": "USB_N", "USB_N": "USB_P"}
    assert pairs_of(["LEAD_A", "SIG"], ("LEAD_A/LEAD_B",)) == {}


def test_an_explicit_pair_takes_a_net_from_its_suffix_partner():
    assert pairs_of(["USB_P", "USB_N", "LEAD_A"], ("*", "USB_P/LEAD_A")) == {"USB_P": "LEAD_A", "LEAD_A": "USB_P"}


def test_a_net_in_two_explicit_pairs_is_refused():
    with pytest.raises(ValueError, match="LEAD_A"):
        explicit_pairs(("LEAD_A/LEAD_B", "LEAD_C/LEAD_A"))
    with pytest.raises(ValueError, match="LEAD_A"):
        explicit_pairs(("LEAD_A/LEAD_A",))


def test_a_malformed_pair_is_refused_when_the_settings_load(tmp_path):
    from placemat.settings import SettingsError, load
    (tmp_path / "placemat.toml").write_text('[route]\ndiff_pairs = ["LEAD_A/LEAD_B", "LEAD_B/LEAD_C"]\n')
    with pytest.raises(SettingsError, match="route.diff_pairs"):
        load(tmp_path)


def test_the_aliases_are_suffix_pairs_no_board_net_takes():
    names = {"LEAD_A", "LEAD_B", "PMPAIR0_P", "LEAD_C", "LEAD_D"}
    aliases = pair_aliases([("LEAD_A", "LEAD_B"), ("LEAD_C", "LEAD_D")], names)
    assert aliases == [("PMPAIR1", "LEAD_A", "LEAD_B"), ("PMPAIR2", "LEAD_C", "LEAD_D")]


def test_an_explicit_pair_counts_its_own_crossings_in_the_run_score():
    from placemat.report import airwires_from_drc

    def edge(net, a, b):
        return {"items": [{"description": "Pad [%s]" % net, "pos": {"x": a[0], "y": a[1]}},
                          {"description": "Pad [%s]" % net, "pos": {"x": b[0], "y": b[1]}}]}
    drc = {"unconnected_items": [edge("LEAD_A", (0, 0), (10, 10)), edge("LEAD_B", (0, 10), (10, 0))]}
    assert airwires_from_drc(drc, ())["crossings_pair"] == 0
    assert airwires_from_drc(drc, (), {"LEAD_A": "LEAD_B", "LEAD_B": "LEAD_A"})["crossings_pair"] == 1


# ---------------------------------------------------------------- the routing copy

NETS = ("LEAD_A", "LEAD_B", "D_P", "D_N", "SIG")


def _board(tmp_path, nets=NETS):
    """A two-part board with one pad per net on each part, a track on
    LEAD_A, and a project giving LEAD_A and LEAD_B a class."""
    from placemat.kicad.quiet import import_pcbnew
    p = import_pcbnew()

    def part(ref, x, y):
        body = "".join('\t\t(pad "%d" smd rect (at %g 0) (size 0.4 1.2) (layers "F.Cu" "F.Mask") (net "%s"))\n'
                       % (i + 1, i * 1.0, net) for i, net in enumerate(nets))
        return ('\t(footprint "t:conn" (layer "F.Cu") (at %g %g)\n\t\t(property "Reference" "%s" (at 0 -2 0) '
                '(layer "F.SilkS"))\n%s\t)\n' % (x, y, ref, body))
    text = ('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
            '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
            '\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n'
            + "".join('\t(net %d "%s")\n' % (i + 1, n) for i, n in enumerate(nets))
            + part("J1", 110, 110) + part("J2", 130, 118)
            + '\t(gr_rect (start 100 100) (end 140 128) (stroke (width 0.1) (type solid)) (fill no) '
              '(layer "Edge.Cuts"))\n)\n')
    pcb = tmp_path / "in.kicad_pcb"
    pcb.write_text(text)
    pro = {"meta": {"filename": "in.kicad_pro", "version": 3},
           "net_settings": {"classes": [{"name": "Default", "clearance": 0.2, "track_width": 0.2},
                                        {"name": "Lead", "clearance": 0.3, "track_width": 0.5,
                                         "diff_pair_gap": 0.3, "diff_pair_width": 0.5}],
                            "netclass_assignments": {"LEAD_A": ["Lead"]},
                            "netclass_patterns": [{"pattern": "LEAD_B", "netclass": "Lead"}]}}
    pcb.with_suffix(".kicad_pro").write_text(json.dumps(pro))
    board = p.LoadBoard(str(pcb))
    if "LEAD_A" in nets:
        t = p.PCB_TRACK(board)
        t.SetStart(p.VECTOR2I(p.FromMM(110), p.FromMM(110)))
        t.SetEnd(p.VECTOR2I(p.FromMM(120), p.FromMM(110)))
        t.SetNetCode(board.GetNetcodeFromNetname("LEAD_A"))
        board.Add(t)
    board.Save(str(pcb))
    return pcb


def _nets(pcb) -> tuple:
    """(the board's net names, the net of each track in order)."""
    from placemat.kicad.quiet import import_pcbnew
    board = import_pcbnew().LoadBoard(str(pcb))
    return ({str(n) for n in board.GetNetsByName().keys() if str(n)},
            [t.GetNetname() for t in board.GetTracks()])


def _classes(pcb) -> dict:
    ns = json.loads(pcb.with_suffix(".kicad_pro").read_text())["net_settings"]
    return ns.get("netclass_assignments") or {}


@needs_kicad
def test_a_rename_and_its_restore_leave_the_board_as_it_was(tmp_path):
    from placemat.kicad.route import rename_nets
    pcb = _board(tmp_path)
    before = _nets(pcb)
    rename_nets(str(pcb), {"LEAD_A": "PMPAIR0_P", "LEAD_B": "PMPAIR0_N"})
    names, tracks = _nets(pcb)
    assert {"PMPAIR0_P", "PMPAIR0_N"} <= names and not {"LEAD_A", "LEAD_B"} & names
    assert tracks == ["PMPAIR0_P"]
    # the pair router reads a net's class by its name: the new names carry the old ones' classes
    assert _classes(pcb)["PMPAIR0_P"] == ["Lead"] and _classes(pcb)["PMPAIR0_N"] == ["Lead"]
    rename_nets(str(pcb), {"PMPAIR0_P": "LEAD_A", "PMPAIR0_N": "LEAD_B"})
    assert _nets(pcb) == before


class _PairRouter:
    """The pair router at its command boundary: records the command and the
    nets of the board it was given, writes its output board with one new
    track on the alias's P net, and prints a summary naming the pair."""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        from placemat.kicad.quiet import import_pcbnew
        p = import_pcbnew()
        inp, out = cmd[2], cmd[3]
        patterns = cmd[cmd.index("--nets") + 1:cmd.index("--layers")]
        self.calls.append((patterns, _nets(inp)[0]))
        board = p.LoadBoard(inp)
        base = next(n for n in patterns if n.startswith("PMPAIR"))
        t = p.PCB_TRACK(board)
        t.SetStart(p.VECTOR2I(p.FromMM(111), p.FromMM(112)))
        t.SetEnd(p.VECTOR2I(p.FromMM(129), p.FromMM(112)))
        t.SetNetCode(board.GetNetcodeFromNetname(base + "_P"))
        board.Add(t)
        board.Save(out)
        summary = {"routed_diff_pairs": [base], "failed_diff_pairs": [], "partial_diff_pairs": [],
                   "single_ended_diff_pairs": [],
                   "pair_reports": [{"pair": base, "p_net": base + "_P", "n_net": base + "_N"}]}
        kw["stdout"].write("JSON_SUMMARY: %s\n" % json.dumps(summary))
        return subprocess.CompletedProcess(cmd, 0)


def _route_pairs(tmp_path, monkeypatch, pairs, nets=NETS):
    import placemat.kicad.route as route_mod
    from placemat.settings import Settings
    router = tmp_path / "router"
    (router / "py_router").mkdir(parents=True)
    (router / "py_router/route_diff.py").write_text("")
    work = tmp_path / "work"
    work.mkdir()
    pcb = _board(work, nets)
    stand_in = _PairRouter()
    monkeypatch.setattr(route_mod.subprocess, "run", stand_in)
    board, result_pairs = route_mod.route_pairs("py", str(router), pcb, work, pairs, ["F.Cu", "B.Cu"], Settings(),
                                                 None, None, 60, {})
    return board, result_pairs, stand_in.calls


@needs_kicad
def test_an_explicit_pair_is_routed_under_its_alias_and_comes_back_under_its_own_names(tmp_path, monkeypatch):
    board, pairs, calls = _route_pairs(tmp_path, monkeypatch, [("LEAD_A", "LEAD_B")])
    [(patterns, given)] = calls
    assert patterns == ["PMPAIR0"]
    assert {"PMPAIR0_P", "PMPAIR0_N"} <= given and not {"LEAD_A", "LEAD_B"} & given
    names, tracks = _nets(board)
    assert {"LEAD_A", "LEAD_B"} <= names and not any(n.startswith("PMPAIR") for n in names)
    assert tracks == ["LEAD_A", "LEAD_A"]          # the script's own track and the router's
    assert pairs.coupled == ["LEAD_A/LEAD_B"] and pairs.routed_nets == {"LEAD_A", "LEAD_B"}
    # the routed copy's project is the board's own, not the alias's
    assert _classes(board) == {"LEAD_A": ["Lead"]}


@needs_kicad
def test_an_explicit_pair_the_board_does_not_have_is_refused_before_routing(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="NO_SUCH_NET"):
        _route_pairs(tmp_path, monkeypatch, [("LEAD_A", "NO_SUCH_NET")])
    assert not (tmp_path / "work" / "pairs.log").exists()


@needs_kicad
def test_a_pair_is_routed_once_under_its_alias(tmp_path, monkeypatch):
    board, pairs, calls = _route_pairs(tmp_path, monkeypatch, [("D_P", "D_N")])
    [(patterns, given)] = calls
    assert patterns == ["PMPAIR0"]
    assert not {"D_P", "D_N"} & given          # the router sees the alias alone, not the real names
    assert pairs.coupled == ["D_P/D_N"] and pairs.routed_nets == {"D_P", "D_N"}
