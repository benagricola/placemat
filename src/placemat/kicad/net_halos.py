"""`[route] net_halos`: a net given a halo (mm) keeps other nets' new copper that far from its own, to keep coupling off
a switch node.

The router takes a per-net clearance map (route.py and route_diff.py `--net-clearances`, a JSON object of net name to
mm) and judges a pair of nets at the larger of the two nets' values. Without one it builds the map itself from the
board's net classes (list_nets.net_clearance_map_by_id: every net in a non-Default class at its strictest class
clearance). With a halo on the board placemat writes the map instead: the router's own class map, built by the
router's own function, with each halo net at the larger of its class clearance and its halo.

Given a map, the router uses it as it stands and does not cap it at `--clearance-ceiling` as it caps its own; placemat
caps the class entries at the ceiling the router args set, and leaves the halos as declared.

Before the route, a pad of another net within a halo net's halo can be left only if its own copper already leads out
past the halo: `trapped` judges the ends of that copper."""
from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path

from ..geometry import point_in_polygon, point_segment_distance, poly_distance

MAP_NAME = "net_clearances.json"            # in the route's work folder; the pair stage's is PAIR_MAP_NAME
PAIR_MAP_NAME = "pairs_net_clearances.json"
_TOUCH_MM = 1e-4                            # copper this close is joined
_EPS = 1e-6


def on_board(halos: dict, nets) -> tuple:
    """The halo entries whose net the board has, and the names of those it does not: ({net: mm}, [name, ...])."""
    names = set(nets)
    return ({n: float(h) for n, h in halos.items() if n in names}, sorted(n for n in halos if n not in names))


def ceiling(args, env) -> float | None:
    """The clearance ceiling the router applies to its own class map, from its command-line flags and environment:
    `--clearance-ceiling`, or `--clearance` under the router's legacy knob (route.py, route_diff.py: `_ceiling`)."""
    args = list(args)
    given = {}
    for i, a in enumerate(args):
        name, eq, value = a.partition("=")
        if name in ("--clearance-ceiling", "--clearance"):
            try:
                given[name] = float(value if eq else args[i + 1])
            except (IndexError, ValueError):
                pass
    if "--clearance-ceiling" in given:
        return given["--clearance-ceiling"]
    if (env or {}).get("KICAD_CLEARANCE_LEGACY_CEILING") == "1" and "--clearance" in given:
        return given["--clearance"]
    return None


def merged(classes: dict, halos: dict, ceiling: float | None = None) -> dict:
    """The map the router is given: {net: mm}, the class map (capped at `ceiling`, as the router caps its own) with each
    halo net at the larger of its class clearance and its halo."""
    out = {n: (min(c, ceiling) if ceiling is not None else c) for n, c in classes.items()}
    for n, h in halos.items():
        out[n] = max(out.get(n, 0.0), float(h))
    return out


_CLASS_MAP = ("import json, sys\n"
              "from list_nets import net_clearance_map_by_id\n"
              "names = json.load(sys.stdin)\n"
              "print('PLACEMAT_CLASS_MAP ' + json.dumps(net_clearance_map_by_id(sys.argv[1], {n: n for n in names})))\n")


def class_clearances(rpy, router_dir, pcb, names, env=None) -> dict:
    """The router's own class map for the board `pcb` (its .kicad_pro beside it), {net: mm}: list_nets'
    net_clearance_map_by_id, run in the router's interpreter. Keyed by name: the function only passes its keys through."""
    proc = subprocess.Popen([str(rpy), "-c", _CLASS_MAP, str(Path(pcb).resolve())], cwd=str(Path(router_dir) / "py_router"),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=dict(env) if env else None)
    out, err = proc.communicate(json.dumps(sorted(names)), timeout=120)
    for line in reversed(out.splitlines()):
        if line.startswith("PLACEMAT_CLASS_MAP "):
            return {str(k): float(v) for k, v in json.loads(line[len("PLACEMAT_CLASS_MAP "):]).items()}
    tail = "\n".join((err or out).splitlines()[-8:])
    raise RuntimeError("the router's net class map could not be read for %s (exit %s)\n%s" % (pcb, proc.returncode, tail))


def write_map(rpy, router_dir, pcb, names, halos: dict, path, ceiling: float | None = None, env=None) -> Path:
    """Write the router's clearance map for `pcb` to `path` and return its absolute path."""
    path = Path(path).resolve()
    path.write_text(json.dumps(merged(class_clearances(rpy, router_dir, pcb, names, env), halos, ceiling),
                               indent=1, sort_keys=True) + "\n")
    return path


# ---------------------------------------------------------------- the trapped-terminal check

def _point_distance(pt, outlines) -> float:
    best = math.inf
    for o in outlines:
        if point_in_polygon(pt, o):
            return 0.0
        for i in range(len(o)):
            best = min(best, point_segment_distance(pt, o[i], o[(i + 1) % len(o)]))
    return best


def _gap(a_outlines, b_outlines) -> float:
    return min((poly_distance(a, b) for a in a_outlines for b in b_outlines), default=math.inf)


def _near(a_box, b_box, reach: float) -> bool:
    return not (a_box.left - reach > b_box.right or b_box.left - reach > a_box.right
                or a_box.top - reach > b_box.bottom or b_box.top - reach > a_box.bottom)


def _component(pad, items) -> list:
    """The tracks, vias and drawn copper of the pad's net joined to the pad, by touching on a shared layer."""
    left = list(items)
    found, frontier = [], [(pad.outlines, pad.layers, pad.box)]
    while frontier and left:
        outlines, layers, box = frontier.pop()
        keep = []
        for c in left:
            if c.layers & layers and _near(box, c.box, _TOUCH_MM) and _gap(outlines, c.outlines) <= _TOUCH_MM:
                found.append(c)
                frontier.append((c.outlines, c.layers, c.box))
            else:
                keep.append(c)
        left = keep
    return found


def _ends(pad, own) -> list:
    """Where the router can lead the pad's net on from: the pad itself, each end of its tracks, each of its vias.
    Drawn copper joins but is not an end. [(point, layers)]."""
    a = pad.airwire_end
    out = [((a.x, a.y), pad.layers)]
    for c in own:
        if c.kind in ("track", "via"):
            out += [(tuple(p), c.layers) for p in c.anchors]
    return out


def trapped(geometry, halos: dict, judged=None) -> list:
    """Every pad of another net inside a halo whose own copper ends inside it too, as records (the facts of its
    `setup.net_halo` finding): the halo net and its halo; the pad (ref, number, its net); `gap_mm`, the pad's own gap
    to the halo net's copper; `reach_mm`, the farthest any end of the pad's copper lies from the halo net's copper on a
    layer they share; `needed_mm`, the halo plus half the pad net's class track width, which a track leaving an end
    needs between its centre and the halo net's copper; `short_mm`, needed less reach. A pad is inside the halo when its copper comes nearer the
    halo net's copper (pads, tracks, vias, drawn copper and pours) than the halo on a layer they share. `judged`: the
    nets to judge (the ones the route routes and has open), None for every net."""
    out = []
    for net, halo in sorted(halos.items()):
        halo = float(halo)
        theirs = [c for c in geometry.copper if c.net == net]
        if not theirs:
            continue
        for fp in geometry.footprints:
            for pad in fp.pads:
                if not pad.net or pad.net == net or pad.no_connect or (judged is not None and pad.net not in judged):
                    continue
                near = [c for c in theirs if c.layers & pad.layers and _near(pad.box, c.box, halo)]
                gap = min((_gap(pad.outlines, c.outlines) for c in near), default=math.inf)
                if gap >= halo - _EPS:
                    continue
                own = _component(pad, [c for c in geometry.copper if c.net == pad.net and c.kind in ("track", "via", "poly")])
                reach = 0.0
                for pt, layers in _ends(pad, own):
                    reach = max(reach, min((_point_distance(pt, c.outlines) for c in theirs if c.layers & layers),
                                           default=math.inf))
                cls = geometry.netclasses.get(pad.net)
                needed = halo + (cls.track_width if cls is not None else 0.0) / 2.0
                if reach >= needed - _EPS:
                    continue
                out.append({"variant": "trapped", "net": net, "halo_mm": halo, "ref": fp.ref, "number": pad.number,
                            "pad_net": pad.net, "gap_mm": round(gap, 3), "reach_mm": round(reach, 3),
                            "needed_mm": round(needed, 3), "short_mm": round(needed - reach, 3)})
    return out


def routed_with_others(halos: dict, open_items: dict, alone=()) -> list:
    """The halo nets the main pass routes, as records: each open (`open_items`, {net: open items} of the nets the
    route routes) and not routed alone first (`alone`, the island nets). The router raises the clearance of every net
    it routes in a call to the largest clearance among them (routing_config.set_net_clearances' floor), so a halo net
    routed with the others spaces all of them at its halo."""
    return [{"variant": "open", "net": n, "halo_mm": float(h), "open_items": int(open_items[n])}
            for n, h in sorted(halos.items()) if open_items.get(n) and n not in set(alone)]


def findings(trapped_records: list, missing: list, halos: dict, open_records=()) -> list:
    """The `setup.net_halo` findings: an entry naming no net on the board, a halo net the main pass routes, then each
    trapped pad."""
    from ..findings import Finding, FindingCause as C
    return ([Finding(C.SETUP_NET_HALO, {"variant": "no_net", "net": n, "halo_mm": float(halos[n])}) for n in missing]
            + [Finding(C.SETUP_NET_HALO, dict(r)) for r in open_records]
            + [Finding(C.SETUP_NET_HALO, dict(r)) for r in trapped_records])
