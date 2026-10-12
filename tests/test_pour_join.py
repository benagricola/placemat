"""A phase that names a pour net joins its pads to the pour by via drops first, then tracks for what is left (D31,
rulings S16 and S17, kicad/pour_join.py)."""
import json
import subprocess

import pytest

from placemat.kicad.pour_join import (REPAIR_FLAGS, PadEnd, PadGroup, drop_command, new_vias, pad_groups,
                                     tasks_to_pour)
from tests.conftest import ROUTER, needs_kicad, needs_router
from tests.test_net_clearance import _two_part_board

W = (("F.Cu", 0.2), ("B.Cu", 0.2))


def _end(ref, x, number="1", shared=False):
    return PadEnd(ref, number, "uuid-" + ref, x, 0.0, shared)


def test_each_group_apart_from_the_pour_gets_one_task_to_the_nearest_joined_pad():
    groups = [PadGroup((_end("C1", 0.0), _end("C2", 10.0)), True),
              PadGroup((_end("C3", 14.0), _end("C4", 30.0)), False),
              PadGroup((_end("C5", -3.0),), False)]
    tasks = tasks_to_pour(groups, "GND", W)
    assert [(t.start, t.end) for t in tasks] == [(("C2", "1"), ("C3", "1")), (("C1", "1"), ("C5", "1"))]
    assert all(t.net == "GND" and t.widths == W and t.apart for t in tasks)


def test_a_task_judged_apart_says_so_in_the_connections_file(tmp_path):
    from placemat.kicad.phase_run import write_connections
    (t,) = tasks_to_pour([PadGroup((_end("C1", 0.0),), True), PadGroup((_end("C2", 5.0),), False)], "GND", W)
    path = write_connections([t], tmp_path / "c.json", ["F.Cu", "B.Cu"])
    assert json.loads(path.read_text())[0]["apart"] is True


def test_a_net_whose_pads_all_reach_one_piece_of_the_pour_gets_no_task():
    assert tasks_to_pour([PadGroup((_end("C1", 0.0), _end("C2", 5.0)), True)], "GND", W) == []


def test_a_group_on_another_piece_of_the_pour_is_joined_to_the_largest():
    """Two groups both reach a pour of the net, on pieces nothing joins (the region joins failed): the smaller group
    is routed to the larger."""
    tasks = tasks_to_pour([PadGroup((_end("C1", 0.0),), True), PadGroup((_end("C2", 5.0), _end("C3", 9.0)), True)],
                          "GND", W)
    assert [(t.start, t.end) for t in tasks] == [(("C1", "1"), ("C2", "1"))]


def test_with_no_group_on_the_pour_the_largest_group_stands_for_it():
    big = PadGroup((_end("C1", 0.0), _end("C2", 1.0)), False)
    tasks = tasks_to_pour([PadGroup((_end("C3", 9.0),), False), big], "GND", W)
    assert [(t.start, t.end) for t in tasks] == [(("C2", "1"), ("C3", "1"))]


def test_an_end_on_a_shared_reference_names_its_footprint():
    tasks = tasks_to_pour([PadGroup((_end("C1", 0.0),), True), PadGroup((_end("TP1", 2.0, shared=True),), False)],
                          "GND", W)
    assert tasks[0].end == ("TP1", "1", "uuid-TP1")


def test_the_drop_call_keeps_the_boards_sizes_and_rules():
    cmd = drop_command("py", "/krt", "in.kicad_pcb", "out.kicad_pcb", "GND", ["F.Cu", "B.Cu"], via_size=0.6,
                       via_drill=0.3, track_width=0.25, pads_file="pads.json", clearances_file="c.json",
                       iterations=500)
    assert cmd[:4] == ["py", "/krt/py_router/repair_planes.py", "in.kicad_pcb", "out.kicad_pcb"]
    assert cmd[cmd.index("--nets") + 1] == "GND"
    assert cmd[cmd.index("--layers") + 1:cmd.index("--layers") + 3] == ["F.Cu", "B.Cu"]
    assert cmd[cmd.index("--via-size") + 1] == "0.6" and cmd[cmd.index("--via-drill") + 1] == "0.3"
    assert cmd[cmd.index("--track-width") + 1] == "0.25" and cmd[cmd.index("--min-track-width") + 1] == "0.25"
    assert cmd[cmd.index("--max-track-width") + 1] == "0.25"            # ruling S16: region joins at the class width
    assert cmd[cmd.index("--escalation") + 1] == "off"
    assert {"--no-fix-drc-settings", "--no-kicad-recheck", "--no-join-gate", "--no-own-pad-lift"} <= set(cmd)
    assert cmd[cmd.index("--pads") + 1] == "pads.json" and cmd[cmd.index("--net-clearances") + 1] == "c.json"
    assert "--rip-blocker-nets" not in cmd
    assert cmd[cmd.index("--max-iterations") + 1] == "500"
    assert {a for a in cmd if a.startswith("--")} <= set(REPAIR_FLAGS)


def test_a_net_with_no_class_sizes_leaves_the_via_to_the_repair():
    cmd = drop_command("py", "/krt", "in", "out", "GND", ["F.Cu"], track_width=0.2)
    assert "--via-size" not in cmd and "--via-drill" not in cmd and "--pads" not in cmd


def _zone(pcb, net, layer, box):
    import pcbnew
    brd = pcbnew.LoadBoard(str(pcb))
    z = pcbnew.ZONE(brd)
    z.SetLayer(layer)
    z.SetNetCode(brd.GetNetcodeFromNetname(net))
    o = z.Outline()
    o.NewOutline()
    x0, y0, x1, y1 = box
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    brd.Add(z)
    pcbnew.ZONE_FILLER(brd).Fill(brd.Zones())
    brd.Save(str(pcb))


def _via(pcb, net, x, y):
    import pcbnew
    brd = pcbnew.LoadBoard(str(pcb))
    v = pcbnew.PCB_VIA(brd)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    v.SetWidth(pcbnew.FromMM(0.45))
    v.SetDrill(pcbnew.FromMM(0.2))
    v.SetNetCode(brd.GetNetcodeFromNetname(net))
    brd.Add(v)
    brd.Save(str(pcb))


@needs_kicad
def test_a_pad_the_pour_covers_is_joined_and_one_it_misses_is_apart(tmp_path):
    pcb = _two_part_board(tmp_path)                 # VIN: U1.3 at (113, 110), J1.2 at (126, 110)
    import pcbnew
    _zone(pcb, "VIN", pcbnew.F_Cu, (125.6, 108, 127, 112))
    got = {tuple(sorted(p.ref for p in g.pads)): g.joined for g in pad_groups(pcb, "VIN")}
    assert got == {("J1",): True, ("U1",): False}


@needs_kicad
def test_a_pad_with_a_via_into_a_plane_on_another_layer_is_joined(tmp_path):
    """A cell's via in its pad joins the pad to an inner or back plane: that pad needs no drop and no track."""
    pcb = _two_part_board(tmp_path)
    import pcbnew
    _zone(pcb, "VIN", pcbnew.B_Cu, (100.5, 100.5, 134.5, 119.5))
    _via(pcb, "VIN", 113, 110)
    got = {tuple(sorted(p.ref for p in g.pads)): g.joined for g in pad_groups(pcb, "VIN")}
    assert got == {("U1",): True, ("J1",): False}


@needs_router
def test_every_flag_of_the_drop_call_is_one_the_routers_plane_repair_parses():
    rpy = ROUTER / ".venv" / "bin" / "python"
    caps = json.loads(subprocess.run([str(rpy), str(ROUTER / "krt_capabilities.py")], capture_output=True, text=True,
                                     cwd=str(ROUTER), timeout=60, check=True).stdout)
    known = set(caps["flags"]["repair_planes.py"])
    cmd = drop_command(rpy, ROUTER, "in", "out", "GND", ["F.Cu"], via_size=0.6, via_drill=0.3, track_width=0.2,
                       pads_file="p.json", clearances_file="c.json", iterations=5)
    assert {a for a in cmd if a.startswith("--")} <= known
    assert set(REPAIR_FLAGS) <= known


@needs_kicad
def test_a_pad_off_the_board_is_in_no_group(tmp_path):
    """A part left outside the outline (a generation's unplaced parts) gets no task."""
    pcb = _two_part_board(tmp_path)
    text = pcb.read_text().replace('(footprint "t:p" (layer "F.Cu") (at 125 110)', '(footprint "t:p" (layer "F.Cu") (at 225 110)')
    pcb.write_text(text)
    refs = sorted(p.ref for g in pad_groups(pcb, "VIN") for p in g.pads)
    assert refs == ["U1"]


@needs_kicad
def test_the_vias_a_call_added_are_named_in_the_pad_or_beside_it(tmp_path):
    import shutil
    pcb = _two_part_board(tmp_path)
    after = tmp_path / "after.kicad_pcb"
    shutil.copy(pcb, after)
    _via(after, "VIN", 113, 110)            # on U1.3: a tap in its pad
    _via(after, "VIN", 118, 115)            # in the open, no track to a pad: a join of the pour's pieces
    _via(after, "VIN", 126, 113)            # beside J1.2, a short track to it: a tap beside its pad
    _track(after, "VIN", (126, 113), (126, 110))
    assert new_vias(pcb, after, "VIN", {("U1", "3"), ("J1", "2")}) == [
        {"at": [113.0, 110.0], "in_pad": True, "tap": True},
        {"at": [118.0, 115.0], "in_pad": False, "tap": False},
        {"at": [126.0, 113.0], "in_pad": False, "tap": True}]


def _track(pcb, net, a, b):
    import pcbnew
    brd = pcbnew.LoadBoard(str(pcb))
    t = pcbnew.PCB_TRACK(brd)
    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[0]), pcbnew.FromMM(a[1])))
    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(b[0]), pcbnew.FromMM(b[1])))
    t.SetWidth(pcbnew.FromMM(0.2))
    t.SetLayer(pcbnew.F_Cu)
    t.SetNetCode(brd.GetNetcodeFromNetname(net))
    brd.Add(t)
    brd.Save(str(pcb))


@needs_kicad
def test_a_pad_in_the_cut_corner_of_an_l_shaped_board_is_in_no_group(tmp_path):
    """Review N7: on the board's outline polygon, not its bounding box. The board is 100..135 x 100..120 with the
    corner x > 120, y < 108 cut away; J1 at (125, 106) stands in the cut."""
    pcb = _two_part_board(tmp_path)
    text = pcb.read_text().replace('(footprint "t:p" (layer "F.Cu") (at 125 110)', '(footprint "t:p" (layer "F.Cu") (at 125 106)')
    text = text.replace('\t(gr_rect (start 100 100) (end 135 120) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))\n',
                        "".join('\t(gr_line (start %g %g) (end %g %g) (stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))\n'
                                % (a + b) for a, b in zip(L, L[1:] + L[:1])))
    pcb.write_text(text)
    assert sorted(p.ref for g in pad_groups(pcb, "VIN") for p in g.pads) == ["U1"]


L = [(100, 100), (120, 100), (120, 108), (135, 108), (135, 120), (100, 120)]
