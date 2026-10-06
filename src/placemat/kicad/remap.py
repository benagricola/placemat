"""A variant's pin remap made on its written board, for the explore to route it as it would stand once the capture
takes the remap (`explore.rank_remapped` with `explore.route_best`). The script and the capture are not touched.

Each group's map (pinmap.plan_summary's `map`: a net moving on part `ref` from one pin to another) gives each pad it
names its new net; a pad a net leaves and none takes is left with no net. The tracks and vias the plan laid from a
pad (the copper of the pad's net that reaches it, end to end) take the pad's new net when they reach no other pad: an
escape or a fanout. Copper that runs on to another pad of the old net would join the new net to it, so it is deleted
and the router lays the connection again; so is copper from a pad left with no net.

A part the remap's best pose turns, on its face and not in a cell, is turned about the centre of its courtyard box
(the turn's `pivot`), as the study turned it; the copper laid from its pads is deleted, since it no longer meets
them, and the router lays it again. Turning a part does not place it again: it may now overlap its neighbours. A
pose that flips a part, or turns a part in a cell (which turns the whole cell), is not made: those parts keep their
pose, with the remap's nets on their pads, and are named in `not_turned`."""
from __future__ import annotations

from .quiet import import_pcbnew, quiet_stderr

pcbnew = import_pcbnew()


def _key(item) -> str:
    return item.m_Uuid.AsString()


def _attached(pad, tracks, pads_of_net) -> tuple:
    """(the tracks and vias of the pad's net, `tracks`, that reach it end to end: those with an end on the pad, and on
    from their other ends, not past another pad of the net, `pads_of_net`; whether they reach one)."""
    def ends(t) -> list:
        return [t.GetPosition()] if isinstance(t, pcbnew.PCB_VIA) else [t.GetStart(), t.GetEnd()]

    def meets(t, u) -> bool:
        """Whether `u` meets `t` at the end `e` of t's, or (t a via) has an end on t."""
        for e in ends(t):
            if any(p.HitTest(e) for p in pads_of_net):
                continue                                  # at a pad: the copper beyond it is that pad's
            if isinstance(u, pcbnew.PCB_VIA) and u.HitTest(e) or e in ends(u):
                return True
        return isinstance(t, pcbnew.PCB_VIA) and any(t.HitTest(f) for f in ends(u))

    others = [p for p in pads_of_net if _key(p) != _key(pad)]
    out = [t for t in tracks if any(pad.HitTest(e) for e in ends(t))]
    seen, frontier = {_key(t) for t in out}, list(out)
    while frontier:
        t = frontier.pop()
        for u in tracks:
            if _key(u) not in seen and meets(t, u):
                seen.add(_key(u))
                out.append(u)
                frontier.append(u)
    reach = any(o.HitTest(e) for t in out for e in ends(t) for o in others) or \
        any(isinstance(t, pcbnew.PCB_VIA) and t.HitTest(o.GetPosition()) for t in out for o in others)
    return out, reach


def _delete(board, item) -> None:
    group = item.GetParentGroup()
    if group is not None:
        group.RemoveItem(item)
    board.Delete(item)


def apply_remap(pcb_path, groups) -> dict:
    """Make the remap of `groups` (explore.remap_of's) on the board at `pcb_path`, saved in place. Returns {"pads": pads
    given a new net, "tracks": tracks and vias given their pad's new net, "deleted": tracks and vias deleted, "turned":
    parts turned, "not_turned": parts whose pose is not made}."""
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(pcb_path))
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}
    nets = {n: board.FindNet(n) for m in (m for g in groups for m in g["map"]) for n in (m["net"],)}
    counts = {"pads": 0, "tracks": 0, "deleted": 0, "turned": [], "not_turned": []}
    for g in groups:
        turning = {}
        for t in g["turns"]:
            if not (t["turn_deg"] or t["flip"]):
                continue
            if t["flip"] or t.get("cell"):
                counts["not_turned"].append(t["ref"])
            else:
                turning[t["ref"]] = t
        new = {}                                          # (ref, pin) -> net: what each pad the map names carries after it
        for m in g["map"]:
            new.setdefault((m["ref"], m["from"]["pin"]), "")
        for m in g["map"]:
            new[(m["ref"], m["to"]["pin"])] = m["net"]
        tracks = list(board.GetTracks())
        plan = []                                         # (pad, net, the copper laid from it)
        for (ref, pin), net in sorted(new.items()):
            fp = by_ref.get(ref)
            if fp is None:
                continue
            for pad in [p for p in fp.Pads() if p.GetNumber() == pin]:
                code = pad.GetNetCode()
                own = [t for t in tracks if t.GetNetCode() == code] if code > 0 else []
                pads_of_net = [p for p in board.GetPads() if p.GetNetCode() == code] if code > 0 else []
                copper, reach = _attached(pad, own, pads_of_net) if own else ([], False)
                plan.append((pad, net, copper, ref in turning or reach or not net))
        gone = set()
        for pad, net, copper, drop in plan:              # every pad's copper found before any net changes
            for t in copper:
                if _key(t) in gone:
                    continue
                if drop:
                    gone.add(_key(t))
                    _delete(board, t)
                    counts["deleted"] += 1
                else:
                    t.SetNet(nets[net])
                    counts["tracks"] += 1
            if net:
                pad.SetNet(nets[net])
            else:
                pad.SetNetCode(0)
            counts["pads"] += 1
        for ref, t in sorted(turning.items()):
            fp = by_ref.get(ref)
            if fp is None:
                continue
            fp.Rotate(pcbnew.VECTOR2I(pcbnew.FromMM(t["pivot"][0]), pcbnew.FromMM(t["pivot"][1])),
                      pcbnew.EDA_ANGLE(t["turn_deg"], pcbnew.DEGREES_T))
            counts["turned"].append(ref)
    board.Save(str(pcb_path))
    return counts
