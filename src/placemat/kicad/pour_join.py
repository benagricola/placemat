"""How a phase that names a pour net joins its pads to the pour (D31, rulings S16 and S17): via drops first, then one
track for each group still apart.

1. The router's plane repair (KRT py_router/repair_planes.py; its pad repair puts a via in the pad, or beside it
   with a short track, plane_pad_tap.py) taps only the pads KiCad's connectivity finds apart from every pour of the
   net (`--pads`); a pad already joined, by a cell's via or any other copper, is left alone. Its region joins tie
   the pieces of the pour together at the net class's track width (ruling S16). Its own multipoint routing of what
   is still split is off (`--no-join-gate`): that is step 2.
2. The net's pads are grouped again. The group holding the most pads among those that reach the pour stands for
   the pour (with none reaching it, the largest group). Each other group is routed to it by one pad-to-pad task
   (`--connections`), from its pad nearest a pad of that group to that pad; the pours are still zones, so the
   track may end on the fill.

`drop_command` is the repair call's command line, `pad_groups` reads the groups off a board (pcbnew), `tasks_to_pour`
picks the tasks (pure), `new_vias` names the vias a call added, and `join_pour` runs the whole of it for one net."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import math
from pathlib import Path
import shutil

REPAIR = "py_router/repair_planes.py"
# the flags drop_command and join_pour give the router (each checked against its capability list: route.py
# _router_lacks_pour_flags)
REPAIR_FLAGS = ("--nets", "--layers", "--via-size", "--via-drill", "--track-width", "--min-track-width",
                "--max-track-width", "--escalation", "--no-fix-drc-settings", "--no-kicad-recheck", "--pads",
                "--no-join-gate", "--no-own-pad-lift", "--net-clearances", "--max-iterations")
TASK_FLAGS = ("--no-own-pad-lift",)


@dataclass(frozen=True)
class PadEnd:
    ref: str
    number: str
    fp: str             # the footprint's uuid
    x: float            # mm
    y: float
    shared: bool = False    # another footprint has its reference: the end names its footprint

    def end(self) -> tuple:
        return (self.ref, self.number, self.fp) if self.shared else (self.ref, self.number)

    def record(self) -> dict:
        from .phase_select import end_record
        return end_record(self.end())


@dataclass(frozen=True)
class PadGroup:
    pads: tuple         # PadEnd, the net's pads one copper group joins
    joined: bool        # the group reaches a pour of the net


def drop_command(python, router_dir, pcb_in, pcb_out, net: str, layers, *, track_width: float,
                 via_size: float | None = None, via_drill: float | None = None, pads_file=None,
                 clearances_file=None, iterations: int | None = None) -> list:
    """The plane repair call for `net` on a board whose pours of it are zones. Taps (a via in the pad, or beside it
    with a track on `layers`) at the net class's via size and drill (left out when unknown: the repair then takes
    the board's Default class) and `track_width`, which also caps the region joins (ruling S16). `--escalation off`:
    no via or clearance below the board's own (the repair's default 'fab' shrinks a tap's via to the fab floor).
    `--no-fix-drc-settings`: the board's project rules are not rewritten (the default lowers them to what the repair
    used). `--no-kicad-recheck` and `--no-join-gate`: the repair lays no track for what is still split; join_pour
    routes it by tasks. `--no-own-pad-lift`: a footprint's own copper blocks every net (an antenna's GND pad is not
    reached across the antenna). `pads_file`: the pads it may tap; `clearances_file`: the capture's stated net
    clearances ({net: mm}), as the route's other calls take them. Rip-up is off (the repair's default), so other
    nets' copper stays as it is."""
    cmd = [str(python), str(Path(router_dir) / REPAIR), str(pcb_in), str(pcb_out), "--nets", net,
           "--layers", *[str(l) for l in layers]]
    if via_size:
        cmd += ["--via-size", "%g" % via_size]
    if via_drill:
        cmd += ["--via-drill", "%g" % via_drill]
    cmd += ["--track-width", "%g" % track_width, "--min-track-width", "%g" % track_width,
            "--max-track-width", "%g" % track_width,
            "--escalation", "off", "--no-fix-drc-settings", "--no-kicad-recheck", "--no-join-gate",
            "--no-own-pad-lift"]
    if pads_file is not None:
        cmd += ["--pads", str(pads_file)]
    if clearances_file is not None:
        cmd += ["--net-clearances", str(clearances_file)]
    if iterations is not None:
        cmd += ["--max-iterations", str(iterations)]
    return cmd


def main_group(groups):
    """The group that stands for the pour: the one with the most pads among those reaching it, or with none reaching
    it the one with the most pads; the first of equals. None with no group."""
    groups = list(groups)
    joined = [g for g in groups if g.joined]
    pool = joined or groups
    return max(pool, key=lambda g: len(g.pads)) if pool else None


def tasks_to_pour(groups, net: str, widths) -> list:
    """One task for each group other than main_group: between its pad nearest a pad of the main group and that pad, ties
    broken by the ends' names, the two ends in (ref, pad) order as an open connection names them (open_connections),
    so the task's record answers the obligation on the same two pads. `widths` ((layer, mm), ...) go on each task.
    Returns phase_select.Task records, in the groups' order."""
    from .phase_select import Task
    groups = list(groups)
    main = main_group(groups)
    out = []
    if main is None or not main.pads:
        return out
    for g in groups:
        if g is main or not g.pads:
            continue
        a, b = min(((a, b) for a in g.pads for b in main.pads),
                   key=lambda ab: (math.hypot(ab[0].x - ab[1].x, ab[0].y - ab[1].y), ab[0].end(), ab[1].end()))
        ends = sorted((a.end(), b.end()), key=lambda e: (e[0], e[1]))
        out.append(Task(net, ends[0], ends[1], tuple(widths)))
    return out


def pad_groups(pcb_path, net: str) -> list:
    """The copper pads of `net` on the board inside its outline (route_cleanup.connected_pad_groups: NPTH pads left
    out), grouped by KiCad's connectivity with every zone filled, each group with whether it reaches a zone of the
    net (the pours are zones on the boards this reads: join_pour's). A pad outside the outline (a part not placed)
    is left out; a pad with no reference or number too."""
    from .quiet import import_pcbnew, quiet_stderr
    from .route_cleanup import connected_pad_groups
    from .write import load_board
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = load_board(str(pcb_path))
        if any(not z.GetIsRuleArea() and z.GetNetname() == net for z in board.Zones()):
            pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    edge = board.GetBoardEdgesBoundingBox()
    inside = (lambda p: edge.Contains(p.GetPosition())) if edge.GetWidth() > 0 and edge.GetHeight() > 0 else \
        (lambda p: True)
    refs = {}
    for fp in board.GetFootprints():
        refs[fp.GetReference()] = refs.get(fp.GetReference(), 0) + 1
    cn = None
    out = []
    for group in connected_pad_groups(board, pcbnew, {net}).get(net, []):
        cn = cn or board.GetConnectivity()
        ends = []
        for p in group:
            fp = p.GetParentFootprint()
            if not fp.GetReference() or not p.GetNumber() or not inside(p):
                continue
            at = p.GetPosition()
            ends.append(PadEnd(fp.GetReference(), p.GetNumber(), fp.m_Uuid.AsString(), at.x / 1e6, at.y / 1e6,
                               refs[fp.GetReference()] > 1))
        if not ends:
            continue
        joined = any(i.GetClass() == "ZONE" and i.GetNetname() == net for i in cn.GetConnectedItems(group[0]))
        out.append(PadGroup(tuple(ends), joined))
    return out


def new_vias(before_pcb, after_pcb, net: str) -> list:
    """The vias of `net` on `after_pcb` that `before_pcb` lacks (by position, to a micrometre), each {"at": [x, y]}
    (mm) with "in_pad": whether its centre is on a pad of the net."""
    from .quiet import import_pcbnew, quiet_stderr
    from .write import load_board
    pcbnew = import_pcbnew()

    def vias(board):
        return {(round(t.GetPosition().x / 1000), round(t.GetPosition().y / 1000)): t for t in board.GetTracks()
                if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == net}
    with quiet_stderr():
        before, after = load_board(str(before_pcb)), load_board(str(after_pcb))
    old = vias(before)
    pads = [p for p in after.GetPads() if p.GetNetname() == net]
    out = []
    for key, v in sorted(vias(after).items()):
        if key in old:
            continue
        at = v.GetPosition()
        out.append({"at": [round(at.x / 1e6, 4), round(at.y / 1e6, 4)], "in_pad": any(p.HitTest(at) for p in pads)})
    return out


def join_pour(ctx, board: Path, out: Path, net: str, width, layers, stem: str, phase: str, common: dict) -> tuple:
    """Join `net`'s pads to its pours on `board`, on `layers` (the phase's), writing `out` (its copper locked):
    the drops, then a task for each group still apart (module doc). Every pour net's partial inner-layer pours are
    guarded on the route's input board; this call takes its own net's guard off for itself and puts it back on
    `out`. The board's project files are copied back over each call's. Returns (record, phase_run.TaskRun):
    {"net", "pads", "joined_before", "apart_before", "tapped", "vias": {"in_pad", "beside"}, "groups_left",
    "tasks": [the router's record of each task]}; pads count those inside the board's outline, "tapped" the pads
    apart before that the drops joined, "groups_left" the groups the tasks were given."""
    from .phase_run import TaskRun, fresh_output, route_tasks
    from .phase_select import _class_widths
    from .route import (RouterFailed, _copy_project, drop_pour_guards, guard_partial_pours, lock_copper,
                        pours_as_zones, pours_back, run_router)
    inp = fresh_output(ctx.work / (stem + "_in.kicad_pcb"))
    shutil.copy(board, inp)
    _copy_project(board, inp)
    drop_pour_guards(str(inp), {net})
    pours_as_zones(str(inp), net)
    widths = tuple((l, width) for l in layers) if width else _class_widths(ctx.geometry, net, layers)
    before = pad_groups(inp, net)
    apart = [p for g in before if not g.joined for p in g.pads]
    dropped, vias = inp, []
    if len(before) > 1:
        dropped = fresh_output(ctx.work / (stem + "_drops.kicad_pcb"))
        pads_file = ctx.work / (stem + "_drops_pads.json")
        pads_file.write_text(json.dumps([p.record() for p in apart], indent=1) + "\n")
        nc = ctx.geometry.netclasses.get(net) or next(
            (c for c in ctx.geometry.netclasses.values() if c.name == "Default"), None)
        cmd = drop_command(ctx.rpy, ctx.router_dir, inp, dropped, net, layers,
                           track_width=max(w for _, w in widths), via_size=nc.via_diameter if nc else None,
                           via_drill=nc.via_drill if nc else None, pads_file=pads_file,
                           clearances_file=ctx.clearances_file, iterations=ctx.iterations)
        log = ctx.work / (stem + "_drops.log")
        rc = run_router(cmd, log, ctx.router_dir, ctx.env, ctx.timeout)
        if rc != 0 or not dropped.exists():
            tail = "\n".join(log.read_text(errors="replace").splitlines()[-8:])
            raise RouterFailed("the router exited %d dropping vias from pour net %s" % (rc, net), rc, log, tail)
        _copy_project(inp, dropped)         # the repair writes a project of its own beside its board
        lock_copper(str(dropped))
        vias = new_vias(inp, dropped, net)
    after = pad_groups(dropped, net) if dropped != inp else before
    pending = tasks_to_pour(after, net, widths)
    task_common = dict(common, extra_args=tuple(common.get("extra_args") or ()) + ("--no-own-pad-lift",))
    # the router's in-run plane finalize (KRT route.py, KICAD_PLANE_FINALIZE) would tap, rip and reconnect the pour
    # net on its own inside a task call; the tasks are the only tracking join_pour asks of it
    tasks_ctx = copy.copy(ctx)
    tasks_ctx.env = dict(ctx.env or {}, KICAD_PLANE_FINALIZE="0")
    run = route_tasks(tasks_ctx, pending, dropped, stem, layers, task_common, phase) if pending \
        else TaskRun(Path(dropped))
    shutil.copy(run.board, out)
    _copy_project(inp, out)
    pours_back(str(out), board)
    lock_copper(str(out))
    guard_partial_pours(str(out), {net}, ctx.layers, ctx.cfg.route_plane_share)
    record = {"net": net, "pads": sum(len(g.pads) for g in before),
              "joined_before": sum(len(g.pads) for g in before if g.joined), "apart_before": len(apart),
              "tapped": sum(1 for p in apart if any(p in g.pads for g in after if g.joined)),
              "vias": {"in_pad": sum(1 for v in vias if v["in_pad"]), "beside": sum(1 for v in vias if not v["in_pad"])},
              "groups_left": len(pending), "tasks": list(run.records)}
    return record, run
