"""A board and a stand-in router for rip and reroute: the stand-in lays copper (straight, or a detour to either side)
and names the nets of the tracks that block a connection, so a route can be blocked by an earlier call's copper."""
import sys
import textwrap
from pathlib import Path

from tests.phase_helpers import fake_capabilities
from tests.test_net_clearance import _project

TOY = textwrap.dedent('''
    import json, math, os, sys
    import pcbnew
    a = sys.argv[1:]
    with open(os.environ["FAKE_ROUTER_LOG"], "a") as f:
        f.write(json.dumps(a) + "\\n")
    def opt(flag):
        return a[a.index(flag) + 1] if flag in a else None
    def opts(flag):
        if flag not in a:
            return []
        i, out = a.index(flag) + 1, []
        while i < len(a) and not a[i].startswith("--"):
            out.append(a[i]); i += 1
        return out
    board = pcbnew.LoadBoard(a[0])
    layers = opts("--layers")
    layer = board.GetLayerID(layers[0])
    mm, CLR = pcbnew.ToMM, 0.15
    def pads_of(net):
        return {(fp.GetReference(), p.GetNumber()): (mm(p.GetPosition().x), mm(p.GetPosition().y))
                for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetname() == net}
    def d_ps(c, p, q):
        dx, dy = q[0] - p[0], q[1] - p[1]
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((c[0] - p[0]) * dx + (c[1] - p[1]) * dy) / L))
        return math.hypot(c[0] - p[0] - t * dx, c[1] - p[1] - t * dy)
    def d_ss(p, q, r, s):
        def cr(o, u, v):
            return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
        if (cr(r, s, p) > 0) != (cr(r, s, q) > 0) and (cr(p, q, r) > 0) != (cr(p, q, s) > 0):
            return 0.0
        return min(d_ps(p, r, s), d_ps(q, r, s), d_ps(r, p, q), d_ps(s, p, q))
    def hits(net, path, w):
        met, blocked = [], False
        for t in board.GetTracks():
            if t.GetNetname() == net or t.GetLayer() != layer or t.Type() == pcbnew.PCB_VIA_T:
                continue
            r, s = (mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))
            if any(d_ss(p, q, r, s) < w / 2 + mm(t.GetWidth()) / 2 + CLR for p, q in zip(path, path[1:])):
                blocked = True
                if t.GetNetname() not in met:
                    met.append(t.GetNetname())
        for fp in board.GetFootprints():
            for pd in fp.Pads():
                c = (mm(pd.GetPosition().x), mm(pd.GetPosition().y))
                if pd.GetNetname() != net and any(d_ps(c, p, q) < w / 2 + 0.3 + CLR for p, q in zip(path, path[1:])):
                    blocked = True
        return blocked, met
    def lay(net, s, e, w):
        d = float(os.environ.get("TOY_DETOUR", "8"))
        L = math.hypot(e[0] - s[0], e[1] - s[1]) or 1.0
        n = (-(e[1] - s[1]) / L, (e[0] - s[0]) / L)
        paths = [[s, e]] + ([[s, (s[0] + n[0] * d * k, s[1] + n[1] * d * k), (e[0] + n[0] * d * k, e[1] + n[1] * d * k), e]
                             for k in (1, -1)] if d else [])
        met = []
        for path in paths:
            blocked, by = hits(net, path, w)
            met += [m for m in by if m not in met]
            if not blocked:
                for p, q in zip(path, path[1:]):
                    t = pcbnew.PCB_TRACK(board)
                    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(p[0]), pcbnew.FromMM(p[1])))
                    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(q[0]), pcbnew.FromMM(q[1])))
                    t.SetWidth(pcbnew.FromMM(w)); t.SetLayer(layer); t.SetNet(board.FindNet(net))
                    board.Add(t)
                if layer != board.GetLayerID(layers[0]):
                    for c in (s, e):            # off the call's first layer: a via at each pad down to the track
                        v = pcbnew.PCB_VIA(board)
                        v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(c[0]), pcbnew.FromMM(c[1])))
                        v.SetWidth(pcbnew.FromMM(0.6)); v.SetDrill(pcbnew.FromMM(0.3))
                        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(board.FindNet(net))
                        board.Add(v)
                return True, sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(path, path[1:])), []
        return False, 0.0, met
    def evidence(met):
        return {"scope": "net", "search": None, "verdicts": [], "narrow": [], "diagnosis": "unknown",
                "blocked_by": [{"found_by": "preexisting", "kind": "copper", "net": m, "ref": None, "pad": None,
                                "layer": None, "at": None, "cells": None, "seen_from": None,
                                "near_source_cells": None, "near_target_cells": None} for m in met]}
    def joined_already(net, s, e):
        for t in board.GetTracks():
            if t.GetNetname() == net and t.Type() != pcbnew.PCB_VIA_T:
                ends_ = {(round(mm(p.x), 3), round(mm(p.y), 3)) for p in (t.GetStart(), t.GetEnd())}
                if ends_ == {(round(s[0], 3), round(s[1], 3)), (round(e[0], 3), round(e[1], 3))}:
                    return True
        return False
    doc, laid = {}, set()
    if "--connections" in a:
        recs = []
        narrow = os.environ.get("TOY_NARROW") if "_rip" not in opt("--connections") else None
        name = os.path.basename(opt("--connections"))
        if os.environ.get("TOY_BLOCKED_LAYER") and "_rip" in name and "_b_" in name:
            layer = board.GetLayerID(os.environ["TOY_BLOCKED_LAYER"])     # an attempt's blocked unit, off its layers
        for t in json.load(open(opt("--connections"))):
            ends = pads_of(t["net"])
            s_, e_ = ends[(t["from"]["ref"], t["from"]["pad"])], ends[(t["to"]["ref"], t["to"]["pad"])]
            if os.environ.get("TOY_JOINED_NARROW") and joined_already(t["net"], s_, e_):
                # KRT's joined_narrow: the ends are already joined by narrower copper; it lays nothing
                recs.append(dict(t, status="joined_narrow", reason=None, joined=True, length_mm=0.0,
                                 min_width_mm={}, layers=layers, path=None, evidence=None))
                continue
            w = max(t["widths"].values()) / (2 if t["net"] == narrow else 1)
            ok, length, met = lay(t["net"], ends[(t["from"]["ref"], t["from"]["pad"])],
                                  ends[(t["to"]["ref"], t["to"]["pad"])], w)
            status = ("joined_narrow" if t["net"] == narrow else "routed") if ok else "failed"
            laid |= {t["net"]} if ok else set()
            recs.append(dict(t, status=status, reason=None, joined=ok, length_mm=length,
                             min_width_mm={l: w for l in t["widths"]} if ok else {}, layers=layers, path=None,
                             evidence=None if ok else evidence(met)))
        doc["connections"] = recs
    else:
        pats = opts("--nets")
        names = sorted({p.GetNetname() for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetname()})
        if pats and pats[0] == "*":
            nets = [n for n in names if "!" + n not in pats]
        else:
            nets = [n for n in names if n in pats]
        powered = dict(zip(opts("--power-nets"), map(float, opts("--power-nets-widths"))))
        doc["net_evidence"], doc["blockers"] = {}, []
        def touched(net, c):
            for t in board.GetTracks():
                if t.GetNetname() != net or t.Type() == pcbnew.PCB_VIA_T:
                    continue
                for e in (t.GetStart(), t.GetEnd()):
                    if math.hypot(mm(e.x) - c[0], mm(e.y) - c[1]) < 1e-3:
                        return True
            return False
        for net in nets:
            ends = sorted(pads_of(net).values())
            anchors = [c for c in ends if touched(net, c)]
            loose = [c for c in ends if c not in anchors]
            if not loose or len(ends) < 2:
                continue
            if not anchors:
                anchors, loose = [loose[0]], loose[1:]
            met = []
            for c in loose:
                target = min(anchors, key=lambda e: math.hypot(e[0] - c[0], e[1] - c[1]))
                ok, _, by = lay(net, target, c, powered.get(net, 0.2))
                if ok:
                    anchors.append(c)
                    laid.add(net)
                met += [m for m in by if m not in met]
            if len(anchors) < len(ends):
                doc["net_evidence"][net] = evidence([])
                doc["blockers"].append({"net": net, "stage": "preexisting",
                                        "blocked_by": [{"net": m, "preexisting": True} for m in met]})
    said = os.environ.get("TOY_SUMMARY_NARROW")         # a net the summary says shipped narrow, its copper not
    if said in laid:
        doc["design_rules"] = {"narrowed": [{"net_name": said, "kind": "track_width", "requested": 0.2,
                                             "delivered": 0.1, "length_mm": 1.0}]}
    board.Save(a[1])
    if "--json-out" in a:
        open(opt("--json-out"), "w").write(json.dumps(doc))
''')

CLASSES = 'def net_clearance_map_by_id(pcb_path, nets, design_rules=None):\n    return {}\n'


def _part(ref, x, y, net, amps=None):
    current = '(property "Pm.I" "%s") ' % amps if amps else ""
    return ('\t(footprint "t:p" (layer "F.Cu") (at %g %g)\n\t\t%s(property "Reference" "%s" (at 0 -2 0) '
            '(layer "F.SilkS"))\n\t\t(pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu" "F.Mask") '
            '(net "%s"))\n\t)\n' % (x, y, current, ref, net))


def rip_board(tmp_path, *, a_track=False, currents=False, third=False, c_net=False, d_net=False,
              p23_track=None) -> Path:
    """Net A: P1.1 (105, 110) to P2.1 (125, 110), with P3.1 (130, 110) when `third`; net B: Q1.1 (115, 104) to
    Q2.1 (115, 116); net C, when `c_net`: R1.1 (113, 104) to R2.1 (113, 116), which A's straight blocks every way, as it
    does B (C's detours, at x = 105 and 121, meet A's track). `currents`: P1 and P2 carry 1 A. `d_net`: the board
    reaches x = 150, with net D, S1.1 (140, 101.5) to S2.1 (140, 123.5), which blocks net E, T1.1 (136, 110) to
    T2.1 (144, 110), every way (E's detours, at y = 102 and 118, meet it), and nothing of A, B or C. `p23_track`: a
    script track of A that wide (mm) from P2.1 to P3.1."""
    pcb = tmp_path / "board" / "layout.kicad_pcb"
    pcb.parent.mkdir()
    amps = "1A" if currents else None
    track = '\t(segment (start 105 110) (end 125 110) (width 0.2) (layer "F.Cu") (net 1))\n' if a_track else ""
    if p23_track:
        track += '\t(segment (start 125 110) (end 130 110) (width %g) (layer "F.Cu") (net 1))\n' % p23_track
    parts = (_part("P1", 105, 110, "A", amps) + _part("P2", 125, 110, "A", amps)
             + (_part("P3", 130, 110, "A") if third else "")
             + _part("Q1", 115, 104, "B") + _part("Q2", 115, 116, "B")
             + (_part("R1", 113, 104, "C") + _part("R2", 113, 116, "C") if c_net else "")
             + (_part("S1", 140, 101.5, "D") + _part("S2", 140, 123.5, "D")
                + _part("T1", 136, 110, "E") + _part("T2", 144, 110, "E") if d_net else ""))
    pcb.write_text('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(general (thickness 1.6))\n'
                   '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n'
                   '\t\t(1 "F.Mask" user)\n\t\t(5 "F.SilkS" user)\n\t)\n'
                   '\t(net 1 "A")\n\t(net 2 "B")\n' + ('\t(net 3 "C")\n' if c_net else "")
                   + ('\t(net 4 "D")\n\t(net 5 "E")\n' if d_net else "")
                   + parts + track
                   + '\t(gr_rect (start 100 100) (end %d 125) (stroke (width 0.1) (type solid)) (fill no) '
                     '(layer "Edge.Cuts"))\n)\n' % (150 if d_net else 135))
    _project(pcb, [{"name": "Default", "clearance": 0.15, "track_width": 0.2}])
    return pcb


def toy_router(tmp_path) -> Path:
    """A router checkout whose route.py is TOY (and whose plane repair is never called here)."""
    krt = tmp_path / "krt"
    (krt / ".venv/bin").mkdir(parents=True)
    (krt / ".venv/bin/python").symlink_to(sys.executable)
    (krt / "py_router").mkdir()
    (krt / "py_router/route.py").write_text(TOY)
    (krt / "py_router/repair_planes.py").write_text(TOY)
    (krt / "py_router/list_nets.py").write_text(CLASSES)
    fake_capabilities(krt)
    (krt / "VERSION").write_text("toy-1\n")
    return krt
