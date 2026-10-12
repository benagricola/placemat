"""How a phase that names a pour net joins its pads to the pour (D31): via drops first, then tracks for what is left.

1. The router's plane repair (KRT py_router/repair_planes.py, its pad repair: a via in the pad, or a via beside it with
   a short track, plane_pad_tap.py) for every pad of the net with no copper to its pour. A pad already joined, by a
   cell's via or any other copper, is left alone.
2. Each group of the net's pads still apart from the pour after that is routed to the pour by one pad-to-pad task
   (`--connections`): from the group's pad nearest a pad the pour reaches, to that pad. The router counts the pour's
   fill round that pad as joining it, so the track may end on the fill.

`drop_command` is the repair call's command line, `pad_groups` reads the groups off a board (pcbnew), and
`tasks_to_pour` picks the tasks (pure)."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

REPAIR = "py_router/repair_planes.py"


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


@dataclass(frozen=True)
class PadGroup:
    pads: tuple         # PadEnd, the net's pads one copper group joins
    joined: bool        # the group reaches the net's pour


def drop_command(python, router_dir, pcb_in, pcb_out, net: str, layers, *, via_size: float, via_drill: float,
                 track_width: float, iterations: int | None = None) -> list:
    """The plane repair call for `net` on a board whose pours of it are zones: taps (a via in the pad, or beside it with
    a track on `layers`) at the net's class via and track sizes. `--escalation off`: no via or clearance below the
    board's own (the repair's default 'fab' shrinks a tap's via to the fab floor and its clearance with it).
    `--no-fix-drc-settings`: the repair does not write its routed floors into the board's project rules (its default
    lowers them to what it used). `--no-kicad-recheck`: the repair's own track reconnect pass is left out; what is
    still apart after the drops is routed by tasks (tasks_to_pour). Rip-up is off (the repair's default), so other
    nets' copper stays as it is."""
    cmd = [str(python), str(Path(router_dir) / REPAIR), str(pcb_in), str(pcb_out), "--nets", net,
           "--layers", *[str(l) for l in layers],
           "--via-size", "%g" % via_size, "--via-drill", "%g" % via_drill,
           "--track-width", "%g" % track_width, "--min-track-width", "%g" % track_width,
           "--escalation", "off", "--no-fix-drc-settings", "--no-kicad-recheck"]
    if iterations is not None:
        cmd += ["--max-iterations", str(iterations)]
    return cmd


def tasks_to_pour(groups, net: str, widths) -> list:
    """One task for each group apart from the pour: from its pad nearest a pad of a joined group to that pad. With no
    group joined, the largest group (then the first) stands for the pour. `widths` ((layer, mm), ...) go on each task.
    Returns phase_select.Task records, in the groups' order."""
    from .phase_select import Task
    groups = list(groups)
    joined = [g for g in groups if g.joined]
    if not joined and groups:
        joined = [max(groups, key=lambda g: len(g.pads))]
    targets = [p for g in joined for p in g.pads]
    out = []
    for g in groups:
        if g in joined or not g.pads or not targets:
            continue
        a, b = min(((a, b) for a in g.pads for b in targets), key=lambda ab: (math.hypot(ab[0].x - ab[1].x,
                                                                                      ab[0].y - ab[1].y),
                                                                           ab[0].end(), ab[1].end()))
        out.append(Task(net, a.end(), b.end(), tuple(widths)))
    return out


def pad_groups(pcb_path, net: str) -> list:
    """The pads of `net` on the board, grouped by KiCad's connectivity with its zones filled, each group with whether
    it reaches a zone of the net (the pours are zones on the boards this reads: route_pour_net's). Pads with no
    reference or number are left out."""
    from .quiet import import_pcbnew, quiet_stderr
    from .write import load_board
    pcbnew = import_pcbnew()
    with quiet_stderr():
        board = load_board(str(pcb_path))
        zones = [z for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname() == net]
        if zones:
            pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    cn = board.GetConnectivity()
    refs = {}
    for fp in board.GetFootprints():
        refs[fp.GetReference()] = refs.get(fp.GetReference(), 0) + 1
    pads, ends = [], {}
    for p in board.GetPads():
        if p.GetNetname() != net:
            continue
        fp = p.GetParentFootprint()
        if not fp.GetReference() or not p.GetNumber():
            continue
        at = p.GetPosition()
        e = PadEnd(fp.GetReference(), p.GetNumber(), fp.m_Uuid.AsString(), at.x / 1e6, at.y / 1e6,
                   refs[fp.GetReference()] > 1)
        pads.append(p)
        ends[p.m_Uuid.AsString()] = e
    out, seen = [], set()
    for p in pads:
        key = p.m_Uuid.AsString()
        if key in seen:
            continue
        reach = cn.GetConnectedItems(p)
        members = [key] + [i.m_Uuid.AsString() for i in reach if i.GetClass() == "PAD" and i.m_Uuid.AsString() in ends]
        members = list(dict.fromkeys(members))
        seen.update(members)
        joined = any(i.GetClass() == "ZONE" and i.GetNetname() == net for i in reach)
        out.append(PadGroup(tuple(ends[m] for m in members), joined))
    return out
