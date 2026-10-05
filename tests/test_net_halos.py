"""`[route] net_halos`: a net given a halo keeps other nets' new copper that far from its own. placemat writes the router's
per-net clearance map itself (the router's own class map, each halo net at the larger of its class clearance and its
halo) and hands it to every router pass. Before the route, a pad of another net inside a halo whose own copper ends
inside it too is a `setup.net_halo` finding: the router cannot lead it out."""
import json
import os
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

from placemat.board_geometry import CopperItem
from placemat.findings import Finding, FindingCause as C
from placemat.kicad import net_halos
from placemat.settings import Settings, SettingsError, bind, load
from placemat.values import Box, CopperLayer
from tests.conftest import needs_kicad
from tests.fixtures import board_geometry, footprint, rect, track

ROUTER = Path(os.environ.get("KRT_DIR", os.path.expanduser("~/work/KRT-upstream")))
needs_router = pytest.mark.skipif(not (ROUTER / "py_router/list_nets.py").exists(), reason="no router at %s" % ROUTER)


# ---------------------------------------------------------------- the setting

def test_the_setting_reads_inline_and_as_a_table(tmp_path):
    (tmp_path / "placemat.toml").write_text('[route]\nnet_halos = {"m.SW" = 2.0, "VSW" = 1}\n')
    assert load(tmp_path).route_net_halos == {"m.SW": 2.0, "VSW": 1}
    (tmp_path / "placemat.toml").write_text('[route.net_halos]\nSW = 1.5\n')
    assert load(tmp_path).route_net_halos == {"SW": 1.5}
    (tmp_path / "placemat.toml").write_text('[route]\n')
    assert load(tmp_path).route_net_halos == {}


@pytest.mark.parametrize("value", ["0", "-1.0", '"2mm"', "true", "[2.0]"])
def test_a_halo_that_is_not_a_positive_number_is_refused(tmp_path, value):
    (tmp_path / "placemat.toml").write_text('[route]\nnet_halos = {"SW" = %s}\n' % value)
    with pytest.raises(SettingsError, match=r"route\.net_halos.*SW.*above 0"):
        load(tmp_path)


@pytest.mark.parametrize("args", [['--net-clearances', 'x.json'], ['--net-clearances=x.json']])
def test_the_router_args_may_not_set_the_clearance_map(tmp_path, args):
    for key in ("router_args", "pair_router_args"):
        (tmp_path / "placemat.toml").write_text('[route]\n%s = %s\n' % (key, json.dumps(args)))
        with pytest.raises(SettingsError, match="--net-clearances is set by placemat itself"):
            load(tmp_path)


def test_a_halo_naming_no_net_is_a_warning_and_is_not_used():
    on, missing = net_halos.on_board({"SW": 2.0, "GONE": 1.0}, {"SW", "FB", "GND"})
    assert on == {"SW": 2.0} and missing == ["GONE"]
    f = net_halos.findings([], missing, {"SW": 2.0, "GONE": 1.0})[0]
    assert f.cause is C.SETUP_NET_HALO and f.severity == "warning"
    assert f.facts == {"variant": "no_net", "net": "GONE", "halo_mm": 1.0}
    assert str(f) == "route.net_halos GONE: no net of that name on this board; the entry is not used"


def test_a_halo_net_the_main_pass_routes_is_a_warning():
    """The router spaces every net of a call at the largest clearance among the nets it routes: an open halo net routed
    with the rest spaces them all at its halo. Routed alone (an island net), or drawn whole, it does not."""
    got = net_halos.routed_with_others({"SW": 2.0, "SW2": 1.0, "SW3": 1.0}, {"SW": 2, "SW3": 1, "FB": 1}, alone={"SW3"})
    assert got == [{"variant": "open", "net": "SW", "halo_mm": 2.0, "open_items": 2}]
    f = net_halos.findings([], [], {"SW": 2.0}, got)[0]
    assert f.cause is C.SETUP_NET_HALO and f.severity == "warning"
    assert str(f).startswith("SW is open (2 item(s)) and routed with the other nets: the router spaces every net of that "
                             "pass 2.00 mm from all copper")


# ---------------------------------------------------------------- the clearance map

def test_the_map_is_the_class_map_with_each_halo_net_at_the_larger_of_the_two():
    classes = {"SW": 0.5, "PWR": 0.3, "SIG": 0.2}
    got = net_halos.merged(classes, {"SW": 0.4, "SIG": 1.0, "VSW": 2.0})
    assert got == {"SW": 0.5, "PWR": 0.3, "SIG": 1.0, "VSW": 2.0}


def test_a_clearance_ceiling_caps_the_classes_as_the_router_would_and_not_the_halos():
    classes = {"SW": 0.5, "PWR": 0.3}
    assert net_halos.merged(classes, {"SW": 2.0}, ceiling=0.25) == {"SW": 2.0, "PWR": 0.25}
    assert net_halos.ceiling(["--clearance-ceiling", "0.25"], {}) == 0.25
    assert net_halos.ceiling(["--clearance-ceiling=0.3"], {}) == 0.3
    assert net_halos.ceiling(["--clearance", "0.2"], {}) is None
    assert net_halos.ceiling(["--clearance", "0.2"], {"KICAD_CLEARANCE_LEGACY_CEILING": "1"}) == 0.2
    assert net_halos.ceiling([], {}) is None


def _project(path: Path, classes, assignments=None, patterns=None):
    ns = {"classes": classes, "netclass_assignments": assignments or {}}
    if patterns:
        ns["netclass_patterns"] = [{"netclass": c, "pattern": p} for p, c in patterns]
    path.with_suffix(".kicad_pro").write_text(json.dumps({"meta": {"filename": path.name, "version": 3}, "net_settings": ns}))


@needs_router
def test_the_class_map_is_the_routers_own(tmp_path):
    """Built by the router's own function (its explicit assignments and pattern globs, the strictest non-Default class
    per net, Default-only nets left out), in the router's own interpreter."""
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb (version 20241229))\n")
    _project(pcb, [{"name": "Default", "clearance": 0.15}, {"name": "Power", "clearance": 0.3},
                   {"name": "Wide", "clearance": 0.5}, {"name": "Equal", "clearance": 0.15}],
             assignments={"VIN": ["Power"], "SW": ["Power"]}, patterns=[("SW*", "Wide"), ("EQ", "Equal")])
    got = net_halos.class_clearances(ROUTER / ".venv/bin/python", ROUTER, pcb, ["VIN", "SW", "SIG", "EQ"])
    assert got == {"VIN": 0.3, "SW": 0.5, "EQ": 0.15}


@needs_router
def test_the_map_file_is_written_where_placemat_puts_it_and_the_router_reads_it(tmp_path):
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb (version 20241229))\n")
    _project(pcb, [{"name": "Default", "clearance": 0.15}, {"name": "Power", "clearance": 0.3}],
             assignments={"VIN": ["Power"], "SW": ["Power"]})
    work = tmp_path / "work"
    work.mkdir()
    path = net_halos.write_map(ROUTER / ".venv/bin/python", ROUTER, pcb, ["VIN", "SW", "SIG"], {"SW": 2.0},
                               work / net_halos.MAP_NAME)
    assert path == (work / "net_clearances.json").resolve() and path.is_absolute()
    assert json.loads(path.read_text()) == {"VIN": 0.3, "SW": 2.0}


# ---------------------------------------------------------------- the router commands carry it

def test_every_router_command_carries_the_map_when_given_one():
    from placemat.kicad.route import pair_command, router_command
    with bind(Settings(route_router_args=("--via-cost", "50"), route_pair_router_args=("--max-turn-angle", "90"))):
        main = router_command("py", "route.py", "in", "out", set(), ["F.Cu"], "s.json", clearances=Path("/w/net_clearances.json"))
        pair = pair_command("py", "route_diff.py", "in", "out", ["A"], ["F.Cu"], clearances=Path("/w/pairs_net_clearances.json"))
        plain = router_command("py", "route.py", "in", "out", set(), ["F.Cu"], "s.json")
    assert main[main.index("--net-clearances") + 1] == "/w/net_clearances.json"
    assert pair[pair.index("--net-clearances") + 1] == "/w/pairs_net_clearances.json"
    assert main[-4:-2] == ["--via-cost", "50"] and pair[-2:] == ["--max-turn-angle", "90"]
    assert "--net-clearances" not in plain


FAKE = textwrap.dedent('''
    import json, os, shutil, sys
    a = sys.argv[1:]
    with open(os.environ["FAKE_ROUTER_LOG"], "a") as f:
        f.write(json.dumps(a) + "\\n")
    shutil.copy(a[0], a[1])
    if "--json-out" in a:
        open(a[a.index("--json-out") + 1], "w").write("{}")
''')

FAKE_LIST_NETS = textwrap.dedent('''
    def net_clearance_map_by_id(pcb_path, nets, design_rules=None):
        return {nid: 0.3 for nid, name in nets.items() if name in ("SW", "VIN")}
''')


def _two_part_board(tmp_path) -> Path:
    """Two parts: U1 with SW, FB and VIN pads, J1 with FB and VIN; SW also drawn as a short track."""
    def part(ref, x, y, pads):
        body = "".join('\t\t(pad "%d" smd rect (at %g 0) (size 0.6 0.6) (layers "F.Cu" "F.Mask") (net "%s"))\n'
                       % (i + 1, at, net) for i, (net, at) in enumerate(pads))
        return ('\t(footprint "t:p" (layer "F.Cu") (at %g %g)\n\t\t(property "Reference" "%s" (at 0 -2 0) '
                '(layer "F.SilkS"))\n%s\t)\n' % (x, y, ref, body))
    nets = ("SW", "FB", "VIN")
    pcb = tmp_path / "board" / "layout.kicad_pcb"
    pcb.parent.mkdir()
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
                   '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
                   '\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n'
                   + "".join('\t(net %d "%s")\n' % (i + 1, n) for i, n in enumerate(nets))
                   + part("U1", 110, 110, [("SW", -1.0), ("FB", 0.0), ("VIN", 3.0)])
                   + part("J1", 125, 110, [("FB", 0.0), ("VIN", 1.0)])
                   + '\t(segment (start 109 110) (end 109 106) (width 0.4) (layer "F.Cu") (net 1))\n'
                   + '\t(gr_rect (start 100 100) (end 135 120) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))\n)\n')
    _project(pcb, [{"name": "Default", "clearance": 0.15, "track_width": 0.2}])
    return pcb


@pytest.fixture
def rig(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    krt = tmp_path / "krt"
    (krt / ".venv/bin").mkdir(parents=True)
    (krt / ".venv/bin/python").symlink_to(sys.executable)
    (krt / "py_router").mkdir()
    (krt / "py_router/route.py").write_text(FAKE)
    (krt / "py_router/list_nets.py").write_text(FAKE_LIST_NETS)
    (krt / "VERSION").write_text("fake-1\n")
    monkeypatch.setenv("FAKE_ROUTER_LOG", str(tmp_path / "calls"))

    class Rig:
        pcb = _two_part_board(tmp_path)
        work = tmp_path / "route"
        router = krt

        def calls(self):
            log = tmp_path / "calls"
            return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
    return Rig()


@needs_kicad
def test_the_island_and_main_passes_carry_one_map_and_the_report_and_its_findings_say_so(rig):
    from placemat.kicad.route import route_board
    said = []
    with bind(Settings(route_net_halos={"SW": 2.0, "GONE": 1.0})):
        report = route_board(rig.pcb, rig.work, router_dir_override=str(rig.router), layers=["F.Cu", "B.Cu"],
                             islands={"VIN": None}, on_setup=said.extend)
    calls = rig.calls()
    assert len(calls) == 2                                           # the island net, then the main pass
    maps = {c[c.index("--net-clearances") + 1] for c in calls}
    assert maps == {str(rig.work.resolve() / "net_clearances.json")}
    assert json.loads(Path(maps.pop()).read_text()) == {"SW": 2.0, "VIN": 0.3}
    assert report.net_halos == {"SW": 2.0} and report.net_halos_missing == ["GONE"]
    # U1.2 (FB) sits 0.4 mm from the SW pad, no copper of its own: trapped. VIN at U1.3 is 3.4 mm off: not judged.
    assert [(r["ref"], r["number"], r["pad_net"]) for r in report.net_halo_trapped] == [("U1", "2", "FB")]
    # the findings were handed over before the first router call ran, and the report carries the same ones
    assert [f.cause for f in said] == [C.SETUP_NET_HALO, C.SETUP_NET_HALO]
    assert {f.facts["variant"] for f in said} == {"trapped", "no_net"}
    assert [f.facts for f in report.findings() if f.cause is C.SETUP_NET_HALO] == [f.facts for f in said]
    d = report.as_dict()
    assert d["net_halos"] == {"SW": 2.0} and d["net_halos_missing"] == ["GONE"] and len(d["net_halo_trapped"]) == 1


@needs_kicad
def test_with_no_halo_on_the_board_no_map_is_passed(rig):
    from placemat.kicad.route import route_board
    with bind(Settings(route_net_halos={"GONE": 1.0})):
        report = route_board(rig.pcb, rig.work, router_dir_override=str(rig.router), layers=["F.Cu", "B.Cu"], islands={})
    assert all("--net-clearances" not in c for c in rig.calls())
    assert report.net_halos == {} and report.net_halos_missing == ["GONE"]


@needs_kicad
def test_the_pair_stage_carries_a_map_of_its_renamed_nets(tmp_path, monkeypatch):
    """The pair router routes a copy whose pair nets are renamed: its map is built on that copy, under those names."""
    import types
    import placemat.kicad.route as route_mod
    from tests.test_pair_layers import _board, _router
    calls, asked = [], []

    def stand_in(cmd, stdout=None, **kw):
        calls.append(list(cmd))
        i = cmd.index("--nets")
        shutil.copy(cmd[i - 2], cmd[i - 1])
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(route_mod.subprocess, "run", stand_in)

    def classes(rpy, router_dir, pcb, names, env=None):
        asked.append((Path(pcb).name, sorted(names)))
        return {n: 0.2 for n in names if n.endswith(("_P", "_N"))}
    monkeypatch.setattr(net_halos, "class_clearances", classes)
    pcb = _board(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    route_mod.route_pairs("py", _router(tmp_path), pcb, work, [("A_P", "A_N"), ("B_P", "B_N")], ["F.Cu", "B.Cu"],
                          Settings(), None, None, 60, {}, halos={"SIG": 1.5, "A_P": 1.0})
    from placemat.pairs import pair_aliases
    renamed = {}
    for base, p, n in pair_aliases([("A_P", "A_N"), ("B_P", "B_N")], ("A_P", "A_N", "B_P", "B_N", "SIG")):
        renamed.update({p: base + "_P", n: base + "_N"})
    assert asked == [("pairs_in.kicad_pcb", sorted(list(renamed.values()) + ["SIG"]))]
    path = Path(calls[0][calls[0].index("--net-clearances") + 1])
    assert path == work.resolve() / "pairs_net_clearances.json"
    got = json.loads(path.read_text())
    assert got[renamed["A_P"]] == 1.0 and got["SIG"] == 1.5 and got[renamed["B_P"]] == 0.2 and "A_P" not in got


# ---------------------------------------------------------------- the trapped-terminal check

def _pads_geometry(*copper, fb_through=False):
    """SW pad (1x1 mm) at (10, 10); FB pad (1x1 mm) at (11.5, 10): 0.5 mm apart, edge to edge."""
    u1 = footprint("U1", 10.75, 10.0, w=2.7, h=1.0, nets=("SW", "FB"))
    sw, fb = u1.pads
    assert (sw.box.center.x, fb.box.center.x) == pytest.approx((10.0, 11.5), abs=1e-9)
    return board_geometry([u1], copper=copper)


def _via(net, x, y, d=0.6):
    outline = rect(x, y, d, d)
    return CopperItem("via", net, frozenset([CopperLayer.F, CopperLayer.B]), (outline,), Box.of_points(outline), None, d,
                      0.3, anchors=((x, y),))


def _poly(net, x0, y0, x1, y1):
    outline = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    return CopperItem("poly", net, frozenset([CopperLayer.F]), (outline,), Box.of_points(outline))


def test_a_pad_with_no_copper_inside_the_halo_is_trapped():
    got = net_halos.trapped(_pads_geometry(), {"SW": 2.0})
    assert len(got) == 1
    r = got[0]
    assert (r["variant"], r["net"], r["halo_mm"], r["ref"], r["number"], r["pad_net"]) == ("trapped", "SW", 2.0, "U1", "2", "FB")
    # its own centre, 1 mm off the SW pad; a 0.2 mm class track needs its centre 2.1 mm off
    assert r["reach_mm"] == pytest.approx(1.0) and r["needed_mm"] == pytest.approx(2.1) and r["short_mm"] == pytest.approx(1.1)
    f = net_halos.findings(got, [], {"SW": 2.0})[0]
    assert str(f) == ("FB pad U1.2 is inside SW's 2.00 mm halo; its copper ends 1.00 mm away where a track leaving it needs "
                      "2.10 mm, 1.10 mm short: draw its escape out past the halo in the module (a longer run= on its "
                      "board.escape), or give SW a smaller halo")


def test_a_pad_whose_escape_ends_inside_the_halo_is_trapped_by_what_the_escape_falls_short():
    got = net_halos.trapped(_pads_geometry(track("FB", 11.5, 10.0, 12.1, 10.0, w=0.3)), {"SW": 2.0})
    assert len(got) == 1
    assert got[0]["reach_mm"] == pytest.approx(1.6) and got[0]["short_mm"] == pytest.approx(0.5)


def test_an_escape_ending_past_the_halo_but_not_half_a_track_past_it_is_still_trapped():
    """A track leaving the end keeps its edge, not its centre, the halo from the switch net: the end needs the halo plus
    half the class track width (0.2 mm here)."""
    got = net_halos.trapped(_pads_geometry(track("FB", 11.5, 10.0, 12.55, 10.0, w=0.3)), {"SW": 2.0})
    assert len(got) == 1
    assert got[0]["reach_mm"] == pytest.approx(2.05) and got[0]["needed_mm"] == pytest.approx(2.1)
    assert got[0]["short_mm"] == pytest.approx(0.05)
    assert net_halos.trapped(_pads_geometry(track("FB", 11.5, 10.0, 12.65, 10.0, w=0.3)), {"SW": 2.0}) == []


def test_a_pad_whose_escape_ends_past_the_halo_is_not_trapped():
    escape = (track("FB", 11.5, 10.0, 12.0, 10.0, w=0.3), track("FB", 12.0, 10.0, 12.0, 13.0, w=0.3))
    assert net_halos.trapped(_pads_geometry(*escape), {"SW": 2.0}) == []


def test_a_pad_with_a_via_past_the_halo_on_its_copper_is_not_trapped():
    """A drawn copper shape leads from the pad out of the halo; it is not an end itself, the via on it is."""
    shape = _poly("FB", 11.2, 9.8, 14.0, 10.2)
    assert len(net_halos.trapped(_pads_geometry(shape), {"SW": 2.0})) == 1
    assert net_halos.trapped(_pads_geometry(shape, _via("FB", 13.5, 10.0)), {"SW": 2.0}) == []


def test_the_halo_is_judged_from_the_halo_nets_drawn_copper_too():
    """FB's escape ends 2.5 mm from the SW pad, but 1.0 mm from a SW track drawn beside it."""
    escape = track("FB", 11.5, 10.0, 13.0, 10.0, w=0.3)
    beside = track("SW", 10.0, 11.0, 14.0, 11.0, w=0.4)          # its edge at y 10.8
    got = net_halos.trapped(_pads_geometry(escape, beside), {"SW": 2.0})
    assert len(got) == 1 and got[0]["reach_mm"] == pytest.approx(0.8) and got[0]["short_mm"] == pytest.approx(1.3)


def test_a_pad_outside_the_halo_or_on_another_layer_or_of_a_net_not_judged_is_left_alone():
    g = _pads_geometry()
    assert net_halos.trapped(g, {"SW": 0.4}) == []                  # FB is 0.5 mm off
    assert net_halos.trapped(g, {"SW": 2.0}, judged={"OTHER"}) == []
    # a SW item only on B.Cu does not reach an F.Cu pad
    far = board_geometry([footprint("U1", 30.0, 30.0, w=2.7, h=1.0, nets=("X", "FB"))],
                         copper=(track("SW", 31.5, 31.0, 34.0, 31.0, w=0.4, layer=CopperLayer.B),))
    assert net_halos.trapped(far, {"SW": 2.0}) == []


# ---------------------------------------------------------------- a real route

def _halo_board(tmp_path) -> Path:
    """A two-layer board. SW is drawn whole: a 0.6 mm track from U1's SW pad up to L1's, a wall from y 104 to y 115.
    FB's pad sits 0.4 mm east of the SW pad with an escape that runs 3.5 mm south, out past a 2 mm halo, to J1 at the
    east edge. EN's pad sits 0.4 mm west of it with no escape. SIG joins J2 west of the wall to J3 east of it."""
    def part(ref, x, y, pads):
        body = "".join('\t\t(pad "%d" smd rect (at %g 0) (size 0.6 0.6) (layers "F.Cu" "F.Mask") (net %d "%s"))\n'
                       % (i + 1, at, NET_IDS[net], net) for i, (net, at) in enumerate(pads))
        return ('\t(footprint "t:p" (layer "F.Cu") (at %g %g)\n\t\t(property "Reference" "%s" (at 0 -2 0) '
                '(layer "F.SilkS"))\n%s\t)\n' % (x, y, ref, body))
    pcb = tmp_path / "board" / "layout.kicad_pcb"
    pcb.parent.mkdir()
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
                   '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
                   '\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n'
                   + "".join('\t(net %d "%s")\n' % (i, n) for n, i in NET_IDS.items())
                   + part("U1", 114.5, 115, [("SW", 0.0), ("FB", 1.0), ("EN", -1.0)])
                   + part("L1", 114.5, 104, [("SW", 0.0)])
                   + part("J1", 140, 125, [("FB", 0.0), ("EN", 2.0)])
                   + part("J2", 104, 110, [("SIG", 0.0)])
                   + part("J3", 126, 110, [("SIG", 0.0)])
                   + '\t(segment (start 114.5 115) (end 114.5 104) (width 0.6) (layer "F.Cu") (net %d))\n' % NET_IDS["SW"]
                   + '\t(segment (start 115.5 115) (end 115.5 118.5) (width 0.25) (layer "F.Cu") (net %d))\n' % NET_IDS["FB"]
                   + '\t(gr_rect (start 100 98) (end 150 130) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))\n)\n')
    _project(pcb, [{"name": "Default", "clearance": 0.15, "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3}])
    return pcb


NET_IDS = {"SW": 1, "FB": 2, "EN": 3, "SIG": 4}


@needs_kicad
@needs_router
def test_a_real_route_keeps_new_copper_the_halo_from_the_switch_net_and_reaches_a_pad_led_out_past_it(tmp_path):
    from placemat.board_geometry import added_copper
    from placemat.geometry import poly_distance
    from placemat.kicad.read import read_board
    from placemat.kicad.route import route_board
    pcb = _halo_board(tmp_path)
    said = []
    with bind(Settings(route_net_halos={"SW": 2.0})):
        report = route_board(pcb, tmp_path / "route", layers=["F.Cu", "B.Cu"], islands={}, on_setup=said.extend)
    # EN has no copper out of the halo: said before the route; FB's escape leads out past it
    assert [(f.facts["ref"], f.facts["number"], f.facts["pad_net"]) for f in said] == [("U1", "3", "EN")]
    assert said[0].facts["reach_mm"] == pytest.approx(0.7, abs=0.01)
    assert "FB" not in report.open_nets and "SIG" not in report.open_nets, report.open_nets
    given, routed = read_board(report.work / "in.kicad_pcb"), read_board(report.routed_pcb)
    sw = [c for c in routed.copper if c.net == "SW"]
    new = [c for c in added_copper(given.copper, routed.copper) if c.net in ("FB", "SIG")]
    assert {c.net for c in new} == {"FB", "SIG"}
    gaps = [poly_distance(a, b) for c in new for s in sw if c.layers & s.layers for a in c.outlines for b in s.outlines]
    assert gaps and min(gaps) >= 2.0 - 0.005, min(gaps)


def test_the_route_command_says_a_trapped_pad_before_the_route_once_and_json_carries_it(tmp_path, monkeypatch, capsys):
    from placemat import cli
    import placemat.kicad.route as route_mod
    from placemat.kicad.route import RouteReport
    pcb = tmp_path / "layout.kicad_pcb"
    pcb.write_text("")
    facts = {"variant": "trapped", "net": "SW", "halo_mm": 2.0, "ref": "U1", "number": "2", "pad_net": "FB", "gap_mm": 0.5,
             "reach_mm": 0.6, "needed_mm": 2.1, "short_mm": 1.5}

    def stand_in(*a, on_setup=None, **kw):
        report = RouteReport(True, 1.0, 1.0, 1, 0, {}, [], [], ["F.Cu"], 1.0, "v", {}, Path("r.kicad_pcb"), Path("r.log"), Path("."))
        report.net_halos, report.net_halo_trapped, report.net_halo_facts = {"SW": 2.0}, [facts], [facts]
        on_setup(report.setup_findings())
        return report
    monkeypatch.setattr(route_mod, "route_board", stand_in)
    assert cli.main(["route", str(pcb)]) == 0
    out = capsys.readouterr().out
    line = "FB pad U1.2 is inside SW's 2.00 mm halo; its copper ends 0.60 mm away where a track leaving it needs 2.10 mm, 1.50 mm short"
    assert out.count(line) == 1 and out.index(line) < out.index("route full")
    assert cli.main(["route", str(pcb), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [d["cause"] for d in doc["finding_details"]] == ["setup.net_halo"]
    assert doc["finding_details"][0]["facts"]["short_mm"] == 1.5 and doc["net_halo_trapped"] == [facts]
