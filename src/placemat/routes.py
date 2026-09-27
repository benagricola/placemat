"""Routed copper kept relative to its pads: `placemat route --adopt NET`
reads the router's new copper on a net off the routed copy, stores each
point as the pad it lies on or an offset from the net's nearest pad in that
pad's part's frame, beside the script in `<script stem>.routes.json`; every
run draws it again while the parts it joins stand as they did relative to
each other, and drops the net, saying why, when one has moved. Routed
coordinates never go into the script."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path

from .copper import Track, Via
from .geometry import point_in_polygon
from .values import CopperLayer, Face, Location

FORMAT = 1


@dataclass(frozen=True)
class RouteEntry:
    net: str
    tracks: tuple                      # {"layer", "width", "a", "b"}: a and b are route points, each
                                       # {"pad": [ref, n], "offset"} on its net's pad or {"anchor": [ref, n], "offset"}
    vias: tuple                        # {"at", "size", "drill"}
    parts: dict = field(default_factory=dict)   # ref -> [x, y, rotation, face] when adopted
    adopted: str = ""


def path_for(script) -> Path:
    script = Path(script)
    return script.with_name(script.stem + ".routes.json")


def read(path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [RouteEntry(e["net"], tuple(e["tracks"]), tuple(e["vias"]), dict(e.get("parts", {})), e.get("adopted", ""))
            for e in data.get("entries", [])]


def write(path, entries) -> None:
    doc = {"format": FORMAT, "entries": [asdict(e) for e in sorted(entries, key=lambda e: e.net)]}
    for e in doc["entries"]:
        e["tracks"], e["vias"] = list(e["tracks"]), list(e["vias"])
    Path(path).write_text(json.dumps(doc, indent=1) + "\n")


def merged(old, new) -> list:
    """`old` with each net in `new` replaced by its new entry."""
    nets = {e.net for e in new}
    return [e for e in old if e.net not in nets] + list(new)


def _turn(dx, dy, degrees):
    from .lock import _turn as turn
    return turn(dx, dy, degrees)


def _key(c) -> tuple:
    pts = tuple(sorted((round(x, 4), round(y, 4)) for x, y in ((a[0], a[1]) if isinstance(a, tuple) else (a.x, a.y)
                                                            for a in c.anchors)))
    return (c.kind, tuple(sorted(l.value for l in c.layers)), pts, round(c.width_mm, 4), round(c.drill_mm, 4))


def _xy(a) -> tuple:
    return (a[0], a[1]) if isinstance(a, tuple) else (a.x, a.y)


def entries_from(placed, routed, nets) -> list:
    """An entry per net of `nets` for the copper the router added to it: in
    `routed`, not in `placed`."""
    had = {_key(c) for c in placed.copper if c.kind in ("track", "via")}
    out = []
    for net in nets:
        new = [c for c in routed.copper if c.net == net and c.kind in ("track", "via") and _key(c) not in had]
        if not new:
            continue
        pads = [(fp, p) for fp in routed.footprints for p in fp.pads if p.net == net]
        used = {}

        def offset(fp, p, xy):
            c = p.box.center
            dx, dy = _turn(xy[0] - c.x, xy[1] - c.y, -fp.rotation)
            return [round(-dx if fp.face is Face.BACK else dx, 6), round(dy, 6)]

        def point(xy):
            for fp, p in pads:                   # on a pad of its own net: that pad, where on it
                if any(point_in_polygon(xy, o) for o in p.outlines):
                    used[fp.ref] = fp
                    return {"pad": [fp.ref, p.number], "offset": offset(fp, p, xy)}
            fp, p = min(pads, key=lambda fp_p: math.dist(xy, (fp_p[1].box.center.x, fp_p[1].box.center.y)))
            used[fp.ref] = fp
            return {"anchor": [fp.ref, p.number], "offset": offset(fp, p, xy)}
        tracks = tuple({"layer": next(iter(c.layers)).value, "width": c.width_mm,
                        "a": point(_xy(c.anchors[0])), "b": point(_xy(c.anchors[-1]))}
                       for c in new if c.kind == "track")
        vias = tuple({"at": point(_xy(c.anchors[0]) if c.anchors else (c.box.center.x, c.box.center.y)),
                      "size": round(c.box.width, 4), "drill": c.drill_mm}
                     for c in new if c.kind == "via")
        parts = {ref: [fp.location.x, fp.location.y, fp.rotation, fp.face.value] for ref, fp in sorted(used.items())}
        import time
        out.append(RouteEntry(net, tracks, vias, parts, time.strftime("%Y-%m-%d")))
    return out


def resolve(entry: RouteEntry, occ, tolerance: float):
    """(tracks, vias) where the entry's copper now lies, or why it cannot be
    drawn: a part it joins is gone, on the other face, or has moved or turned
    relative to the others since it was adopted."""
    refs = sorted(entry.parts)
    for ref in refs:
        if ref not in occ.items:
            return "%s is no longer on the board" % ref
    now = {ref: occ.items[ref].reference for ref in refs}
    base, was = refs[0], entry.parts[refs[0]]
    for ref in refs:
        x, y, r, face = entry.parts[ref]
        p = now[ref]
        if p.face.value != face:
            return "%s is on the other face now" % ref
        then = _turn(x - was[0], y - was[1], -was[2])
        rel = _turn(p.location.x - now[base].location.x, p.location.y - now[base].location.y,
                    -now[base].rotation)
        turned = ((p.rotation - now[base].rotation) - (r - was[2]) + 180.0) % 360.0 - 180.0
        if math.dist(then, rel) > tolerance or abs(turned) > max(tolerance * 10, 0.01):
            return "%s has moved or turned relative to %s since it was adopted" % (ref, base)

    def locate(pt):
        ref, number = pt["pad"] if "pad" in pt else pt["anchor"]
        c = occ.pad_location(ref, number)
        dx, dy = pt["offset"]
        g = now[ref]
        vx, vy = _turn(-dx if g.face is Face.BACK else dx, dy, g.rotation)
        return Location(round(c.x + vx, 6), round(c.y + vy, 6))
    tracks = [Track(entry.net, CopperLayer.of(t["layer"]), t["width"], locate(t["a"]), locate(t["b"]))
              for t in entry.tracks]
    vias = [Via(entry.net, locate(v["at"]), v["drill"], v["size"]) for v in entry.vias]
    return tracks, vias


def adopt(script, placed, routed, nets=None, still_open=(), shorted=()) -> list:
    """Adopt the router's new copper on `nets` (None: every net it added
    copper to) into the script's routes file, merged over what it held. A
    net still open or shorted after the route is left out: a net is adopted
    whole and clean. The entries written."""
    if nets is None:
        had = {_key(c) for c in placed.copper if c.kind in ("track", "via")}
        nets = sorted({c.net for c in routed.copper if c.kind in ("track", "via") and c.net and _key(c) not in had})
    nets = [n for n in nets if n not in still_open and n not in shorted]
    new = entries_from(placed, routed, nets)
    if new:
        path = path_for(script)
        write(path, merged(read(path), new))
    return new


def release(script, nets) -> list:
    """Drop `nets` from the script's routes file; the nets it did not hold."""
    path = path_for(script)
    old = read(path)
    held = {e.net for e in old}
    write(path, [e for e in old if e.net not in set(nets)])
    return [n for n in nets if n not in held]


def describe(entry: RouteEntry) -> str:
    return "%-20s %d track(s), %d via(s), joining %s, adopted %s" % (
        entry.net, len(entry.tracks), len(entry.vias), ", ".join(sorted(entry.parts)) or "-", entry.adopted or "-")


def summary(plan) -> str:
    """How a plan's adopted routes fared, for the run's log: "" when it had none."""
    if not plan.adopted:
        return ""
    held = [n for n, s in plan.adopted.items() if s == "held"]
    dropped = {n: s[len("dropped: "):] for n, s in plan.adopted.items() if s != "held"}
    line = "%d held, %d dropped" % (len(held), len(dropped))
    if dropped:
        line += " (%s)" % "; ".join("%s: %s" % kv for kv in sorted(dropped.items()))
    return line
