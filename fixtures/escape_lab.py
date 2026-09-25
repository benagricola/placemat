"""The escape lab: whether a chip's pins escape, by the router against
placemat's escape model (docs/superpowers/specs/2026-09-25-escape-routability-design.md).

Each case is a board built here: the chip at the origin of its own frame,
every signal pin netted to its own sink pad on a ring well outside it (so a
failure is the escape, not the rest of the route), the exposed pad on
ground, and whatever parts the case adds. Each case is routed twice with the
router `placemat route` drives:

- `one`: signal on F.Cu only, a ground plane on B.Cu;
- `two`: signal on both layers.

Per pin it records what the router did (connected or not; on the pin's layer
or through vias; routed length against the straight run) and what placemat
says of the same board at several escape depths (the search's view of the
pin's corridors, the findings' path search, crossed escapes).

    python fixtures/escape_lab.py --chip PATH.kicad_mod --out DIR [--case bare] [--case cap] [--jobs N]

Results: DIR/results.json, one record per (case, setup, pin), and each
case's boards and routes under DIR/<case>/<setup>/.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import json
import math
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CAP_LIB = "/usr/share/kicad/footprints/Capacitor_SMD.pretty"
DEPTHS = (0.3, 0.6, 1.0, 1.5, 2.0, 3.0)
SINK_OUT = 6.0          # mm from the pad row's outer edge to the sinks
SINK_SPREAD = 2.5       # the sinks' pitch as a multiple of the pins'
SINK_PAD = 0.6
MARGIN = 5.0            # board edge past the sinks
GROUND = "GND"


@dataclasses.dataclass(frozen=True)
class NetClass:
    track: float = 0.2
    clearance: float = 0.2
    via: float = 0.6
    drill: float = 0.3

    @property
    def name(self):
        return "t%gc%g" % (self.track, self.clearance)


@dataclasses.dataclass(frozen=True)
class Extra:
    """A part the case adds: a footprint from `lib`, placed in the chip's
    frame, its pads on the nets named (pad number -> net; a net named for a
    chip pin, "P<n>", joins that pin)."""
    lib: str
    name: str
    ref: str
    x: float
    y: float
    rotation: float
    nets: tuple         # ((pad number, net), ...)


@dataclasses.dataclass(frozen=True)
class Case:
    name: str
    nc: NetClass = NetClass()
    extras: tuple = ()
    served: tuple = ()  # chip pins a part serves: no sink of their own


# ------------------------------------------------------------ the chip
def _pcbnew():
    from placemat.kicad.quiet import import_pcbnew
    return import_pcbnew()


def load_footprint(path_or_lib, name=None):
    pcbnew = _pcbnew()
    if name is None:
        p = Path(path_or_lib)
        return pcbnew.FootprintLoad(str(p.parent), p.stem)
    return pcbnew.FootprintLoad(path_or_lib, name)


def chip_pins(chip_path) -> dict:
    """number -> (x, y, w, h, face) in the chip's frame; face is the side
    ('w', 'e', 'n', 's') of a pin row, or '' for a pad inside them."""
    pcbnew = _pcbnew()
    fp = load_footprint(chip_path)
    pads = {}
    for p in fp.Pads():
        if not p.GetNumber():
            continue
        pos, size = p.GetPosition(), p.GetSize(pcbnew.F_Cu)
        pads[p.GetNumber()] = (pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y), pcbnew.ToMM(size.x), pcbnew.ToMM(size.y))
    xs = [v[0] for v in pads.values()]
    ys = [v[1] for v in pads.values()]
    out = {}
    for n, (x, y, w, h) in pads.items():
        face = ""
        if w > h and abs(x) > 0.9 * max(abs(v) for v in xs):
            face = "w" if x < 0 else "e"
        elif h > w and abs(y) > 0.9 * max(abs(v) for v in ys):
            face = "n" if y < 0 else "s"
        out[n] = (x, y, w, h, face)
    return out


def row_frame(pin):
    """(outward unit, along unit) for a pin's row."""
    face = pin[4]
    return {"w": ((-1.0, 0.0), (0.0, 1.0)), "e": ((1.0, 0.0), (0.0, 1.0)),
            "n": ((0.0, -1.0), (1.0, 0.0)), "s": ((0.0, 1.0), (1.0, 0.0))}[face]


def pad_edge(pin) -> float:
    """How far the pin's row's outer edge is from the chip's centre."""
    x, y, w, h, face = pin
    return abs(x) + w / 2 if face in "we" else abs(y) + h / 2


def sink_at(pin, edge):
    (ox, oy), (ax, ay) = row_frame(pin)
    x, y = pin[0], pin[1]
    along = x * ax + y * ay
    d = edge + SINK_OUT
    return ox * d + ax * along * SINK_SPREAD, oy * d + ay * along * SINK_SPREAD


# ------------------------------------------------------------ building a board
def project_json(nc: NetClass) -> dict:
    rules = {"min_clearance": 0.0, "min_track_width": min(0.1, nc.track), "min_via_diameter": min(0.4, nc.via),
             "min_through_hole_diameter": min(0.2, nc.drill), "min_via_annular_width": 0.05,
             "min_copper_edge_clearance": 0.3, "min_hole_clearance": 0.2, "min_hole_to_hole": 0.2}
    cls = {"name": "Default", "clearance": nc.clearance, "track_width": nc.track, "via_diameter": nc.via,
           "via_drill": nc.drill, "microvia_diameter": 0.3, "microvia_drill": 0.1, "diff_pair_width": nc.track,
           "diff_pair_gap": nc.clearance, "diff_pair_via_gap": nc.clearance, "priority": 2147483647,
           "bus_width": 12, "wire_width": 6, "line_style": 0}
    return {"board": {"design_settings": {"rules": rules, "defaults": {}, "meta": {"version": 2}}},
            "net_settings": {"classes": [cls], "meta": {"version": 5}, "net_colors": None,
                             "netclass_assignments": None, "netclass_patterns": []},
            "meta": {"filename": "board.kicad_pro", "version": 3}}


def build(case: Case, setup: str, chip_path: str, out: Path) -> tuple:
    """The case's board at out/board.kicad_pcb; returns (path, {signal net: (pin, sink xy)})."""
    pcbnew = _pcbnew()
    out.mkdir(parents=True, exist_ok=True)
    mm = pcbnew.FromMM
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    nets = {}

    def net(name):
        if name not in nets:
            ni = pcbnew.NETINFO_ITEM(board, name)
            board.Add(ni)
            nets[name] = ni
        return nets[name]

    cx = cy = 50.0
    pins = chip_pins(chip_path)
    edge = max(pad_edge(p) for p in pins.values() if p[4])
    chip = load_footprint(chip_path)
    chip.SetReference("U1")
    chip.SetPosition(pcbnew.VECTOR2I(mm(cx), mm(cy)))
    board.Add(chip)
    signals = {}
    for p in chip.Pads():
        n = p.GetNumber()
        if not n:
            continue
        if not pins[n][4]:
            p.SetNet(net(GROUND))
            continue
        name = "P%s" % n
        p.SetNet(net(name))
        if n not in case.served:
            signals[name] = (n, sink_at(pins[n], edge))
    k = 0
    for name, (n, (sx, sy)) in sorted(signals.items()):
        k += 1
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference("TP%d" % k)
        pad = pcbnew.PAD(fp)
        pad.SetShape(pcbnew.PAD_SHAPE_RECT)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetSize(pcbnew.VECTOR2I(mm(SINK_PAD), mm(SINK_PAD)))
        ls = pcbnew.LSET()
        ls.AddLayer(pcbnew.F_Cu)
        ls.AddLayer(pcbnew.F_Mask)
        pad.SetLayerSet(ls)
        pad.SetNumber("1")
        fp.Add(pad)
        fp.SetPosition(pcbnew.VECTOR2I(mm(cx + sx), mm(cy + sy)))
        pad.SetNet(net(name))
        board.Add(fp)
    for e in case.extras:
        fp = load_footprint(e.lib, e.name)
        fp.SetReference(e.ref)
        fp.SetPosition(pcbnew.VECTOR2I(mm(cx + e.x), mm(cy + e.y)))
        fp.SetOrientationDegrees(e.rotation)
        byn = dict(e.nets)
        for p in fp.Pads():
            if p.GetNumber() in byn:
                p.SetNet(net(byn[p.GetNumber()]))
        board.Add(fp)
    half = edge + SINK_OUT + MARGIN
    corners = [(cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half)]
    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetStart(pcbnew.VECTOR2I(mm(x0), mm(y0)))
        s.SetEnd(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        s.SetWidth(mm(0.1))
        board.Add(s)
    if setup == "one":
        z = pcbnew.ZONE(board)
        z.SetLayer(pcbnew.B_Cu)
        z.SetNet(net(GROUND))
        z.SetLocalClearance(mm(case.nc.clearance))
        z.SetMinThickness(mm(0.2))
        chain = pcbnew.SHAPE_LINE_CHAIN()
        for x, y in corners:
            chain.Append(mm(x + 0.5 * (1 if x < cx else -1)), mm(y + 0.5 * (1 if y < cy else -1)))
        chain.SetClosed(True)
        z.Outline().AddOutline(chain)
        board.Add(z)
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    path = out / "board.kicad_pcb"
    pcbnew.SaveBoard(str(path), board)          # writes a default project beside it: replaced below
    (out / "board.kicad_pro").write_text(json.dumps(project_json(case.nc), indent=2))
    return path, {name: (n, (cx + sx, cy + sy)) for name, (n, (sx, sy)) in signals.items()}, (cx, cy)


# ------------------------------------------------------------ what the router did
def route(path: Path, setup: str, work: Path):
    from placemat.kicad.route import route_board
    layers = ["F.Cu"] if setup == "one" else ["F.Cu", "B.Cu"]
    return route_board(path, work, exclude_nets={GROUND}, layers=layers, quick=False)


def routed_nets(pcb_out: Path) -> dict:
    """net -> {"vias": n, "length": mm, "layers": set}"""
    pcbnew = _pcbnew()
    b = pcbnew.LoadBoard(str(pcb_out))
    out = {}
    for t in b.GetTracks():
        r = out.setdefault(t.GetNetname(), {"vias": 0, "length": 0.0, "layers": set()})
        if isinstance(t, pcbnew.PCB_VIA):
            r["vias"] += 1
        else:
            r["length"] += pcbnew.ToMM(t.GetLength())
            r["layers"].add(t.GetLayerName())
    return out


# ------------------------------------------------------------ what placemat says
def placemat_view(path: Path, depth: float) -> dict:
    """number -> the chip pin's escape as placemat sees it at `depth`."""
    from placemat.kicad.read import read_board
    from placemat.layout import Board
    from placemat.settings import Settings
    from placemat.values import Net, Part
    g = read_board(path)
    cfg = dataclasses.replace(Settings(), cleanup_enabled=False, place_escape_depth=depth)
    b = Board(g, edge_margin=0.3, settings=cfg, keep_going=True)
    for fp in g.footprints:
        b.place(Part(fp.inst), at=fp.location, rotation=fp.rotation)
    b.free_net(Net(GROUND))
    plan = b.resolve()
    occ = plan.occupancy
    esc = occ.escapes()
    closed, walled = esc.confirmed()
    closed = {n for r, n, *_ in closed if r == "U1"}
    walled = {n for r, n, *_ in walled if r == "U1"}
    crossed = {}
    for n, e, f in occ.ratsnest().crossed_pair_list(depth):
        if n != "U1":
            continue
        for edge in (e, f):
            end = edge.a if edge.a.ref == "U1" else edge.b
            crossed[end.number] = crossed.get(end.number, 0) + 1
    out = {}
    for c in esc._corr.get("U1", ()):
        r = out.setdefault(c.number, {"strips": 0, "strips_open": 0, "vias": 0, "vias_open": 0})
        ok = bool(esc._open.get(id(c)))
        if c.via:
            r["vias"] += 1
            r["vias_open"] += ok
        else:
            r["strips"] += 1
            r["strips_open"] += ok
    for n, r in out.items():
        r["search"] = "walled" if not (r["strips_open"] or r["vias_open"]) else (
            "strip" if r["strips_open"] else "via")
        r["finding"] = "walled" if n in walled else ("closed" if n in closed else "")
        r["crossed"] = crossed.get(n, 0)
    return out


# ------------------------------------------------------------ one case
def run_case(case: Case, setup: str, chip_path: str, root: str) -> list:
    out = Path(root) / case.name / setup
    shutil.rmtree(out, ignore_errors=True)
    # Built in a fresh process: KiCad keeps a project it has saved, so a board
    # read back in the process that wrote it has the default net class.
    import multiprocessing
    with concurrent.futures.ProcessPoolExecutor(1, mp_context=multiprocessing.get_context("spawn")) as ex:
        path, signals, _ = ex.submit(build, case, setup, chip_path, out).result()
    rep = route(path, setup, out / "route")
    nets = routed_nets(rep.routed_pcb)
    views = {d: placemat_view(path, d) for d in DEPTHS}
    pins = chip_pins(chip_path)
    served = {int(n) for n in case.served}
    rows = []
    for number, (x, y, w, h, face) in sorted(pins.items(), key=lambda kv: int(kv[0])):
        if not face:
            continue
        name = "P%s" % number
        r = nets.get(name, {"vias": 0, "length": 0.0, "layers": set()})
        sink = signals.get(name)
        straight = math.hypot(sink[1][0] - 50.0 - x, sink[1][1] - 50.0 - y) if sink else None
        rows.append({
            "case": case.name, "setup": setup, "pin": number, "face": face,
            "from_served": min((abs(int(number) - s) for s in served), default=None),
            "routed": rep.open_nets.get(name, 0) == 0,
            "vias": r["vias"], "layers": sorted(r["layers"]), "length": round(r["length"], 3),
            "straight": round(straight, 3) if straight else None,
            "placemat": {str(d): views[d].get(number) for d in DEPTHS},
        })
    (out / "rows.json").write_text(json.dumps(rows, indent=1))
    summary = {"case": case.name, "setup": setup, "closure": rep.closure, "closure_clean": rep.closure_clean,
               "open_after": rep.open_after, "open_nets": rep.open_nets, "seconds": rep.seconds, "valid": rep.valid,
               "invalid": rep.invalid_reason}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    return rows


# ------------------------------------------------------------ the cases
def bare_cases():
    return [Case("bare-" + nc.name, nc) for nc in (NetClass(0.2, 0.2, 0.6, 0.3), NetClass(0.15, 0.15, 0.45, 0.25),
                                                    NetClass(0.1, 0.1, 0.4, 0.2))]


def _turned(lib, name, rotation):
    """The footprint turned by `rotation` at the origin: its pads' copper as
    point lists, pad number -> [(x, y)], in mm."""
    pcbnew = _pcbnew()
    fp = load_footprint(lib, name)
    fp.SetPosition(pcbnew.VECTOR2I(0, 0))
    fp.SetOrientationDegrees(rotation)
    out = {}
    for q in fp.Pads():
        poly = q.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_INSIDE)
        chain = poly.Outline(0)
        out[q.GetNumber()] = [(pcbnew.ToMM(chain.CPoint(i).x), pcbnew.ToMM(chain.CPoint(i).y))
                              for i in range(chain.PointCount())]
    return out


def _centre(pts):
    return sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)


def cap_cases(chip_path, pin: str, size="C_0402_1005Metric", nc=NetClass()):
    """One cap on `pin`: pad 1 on the pin's net, pad 2 on ground, over a grid
    of turns (radial: pad 1 toward the pin, pad 2 straight out; tangential:
    along the row; diagonal: 45 degrees between), slides along the row and
    gaps from the pin row's outer edge to the cap's nearest copper."""
    pins = chip_pins(chip_path)
    p = pins[pin]
    (ox, oy), (ax, ay) = row_frame(p)
    edge = pad_edge(p)
    s2 = math.sqrt(0.5)
    wants = {"radial": (ox, oy), "tangential": (ax, ay), "diagonal": ((ox + ax) * s2, (oy + ay) * s2)}
    out = []
    for turn, (wx, wy) in wants.items():
        best = None
        for rot in range(0, 360, 45):
            pads = _turned(CAP_LIB, size, float(rot))
            (x1, y1), (x2, y2) = _centre(pads["1"]), _centre(pads["2"])
            n = math.hypot(x2 - x1, y2 - y1)
            score = ((x2 - x1) * wx + (y2 - y1) * wy) / n
            if best is None or score > best[0] + 1e-9:
                best = (score, rot, pads)
        _, rot, pads = best
        nearest = min(x * ox + y * oy for pts in pads.values() for x, y in pts)   # nearest copper, outward
        for slide in (0.0, 0.4, 0.8, 1.2):
            for gap in (0.2, 0.5, 1.0, 1.5, 2.0):
                d = edge + gap - nearest
                along = p[0] * ax + p[1] * ay + slide
                x, y = ox * d + ax * along, oy * d + ay * along
                name = "cap-%s-%s-s%g-g%g" % (size.split("_")[1], turn, slide, gap)
                out.append(Case(name, nc, (Extra(CAP_LIB, size, "C1", x, y, float(rot),
                                                 (("1", "P%s" % pin), ("2", GROUND))),), (pin,)))
    return out


def _run(args):
    return run_case(*args)


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chip", required=True, help="the chip's .kicad_mod")
    ap.add_argument("--out", required=True)
    ap.add_argument("--case", action="append", choices=("bare", "cap"))
    ap.add_argument("--pin", default=None, help="cap: the chip pin it serves (default: the middle of the first row)")
    ap.add_argument("--setup", action="append", choices=("one", "two"))
    ap.add_argument("--only", help="run only the cases whose name contains this")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    a = ap.parse_args(argv)
    kinds = a.case or ["bare", "cap"]
    setups = a.setup or ["one", "two"]
    pins = chip_pins(a.chip)
    row = sorted((n for n, p in pins.items() if p[4] == pins[min(pins, key=lambda n: int(n))][4]), key=int)
    pin = a.pin or row[len(row) // 2]
    cases = []
    if "bare" in kinds:
        cases += bare_cases()
    if "cap" in kinds:
        cases += cap_cases(a.chip, pin)
    if a.only:
        cases = [c for c in cases if a.only in c.name]
    jobs = [(c, s, a.chip, a.out) for c in cases for s in setups]
    rows = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.jobs) as pool:
        for got in pool.map(_run, jobs):
            rows += got
            if got:
                r0 = got[0]
                bad = [r["pin"] for r in got if not r["routed"]]
                print("%-40s %-3s routed %d/%d, vias %d%s" % (
                    r0["case"], r0["setup"], sum(r["routed"] for r in got), len(got), sum(r["vias"] for r in got),
                    ("; open " + ",".join(bad[:12])) if bad else ""), flush=True)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "results.json").write_text(json.dumps(rows, indent=0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
