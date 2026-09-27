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

from .board_geometry import added_copper
from .copper import Track, Via
from .geometry import point_in_polygon
from .values import Box, CopperLayer, Location

FORMAT = 1


@dataclass(frozen=True)
class RouteEntry:
    net: str
    tracks: tuple                      # {"layer", "width", "a", "b"}: a and b are route points, each
                                       # {"pad": [ref, n], "offset"} on its net's pad or {"anchor": [ref, n], "offset"}
    vias: tuple                        # {"at", "size", "drill"}
    parts: dict = field(default_factory=dict)   # ref -> {"face", "pads": {number: [x, y]}} when adopted
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


def _xy(a) -> tuple:
    return (a[0], a[1]) if isinstance(a, tuple) else (a.x, a.y)


def _pad_centres(fp) -> dict:
    """{number: centre} of a part's pads, pads sharing a number as one: the
    centre of their union, as Occupancy.pad_location gives it."""
    boxes = {}
    for p in fp.pads:
        boxes.setdefault(p.number, []).append(p.box)
    return {n: Box.union(bs).center for n, bs in boxes.items()}


def _spread(centres: dict) -> list:
    """The two pad numbers farthest apart: with the bound pads, enough to see
    a part turn."""
    items = sorted(centres.items())
    best, pair = -1.0, items[:1]
    for i, (na, a) in enumerate(items):
        for nb, b in items[i + 1:]:
            d = a.distance(b)
            if d > best:
                best, pair = d, [(na, a), (nb, b)]
    return [n for n, _ in pair]


def entries_from(placed, routed, nets) -> list:
    """An entry per net of `nets` for the copper the router added to it: in
    `routed`, not in `placed`. Each point is kept as an offset from a pad of
    its net - the pad it lies on, else the nearest - and each part it binds
    to by the centres of those pads and of its two farthest-apart ones, in
    the board's frame, so a later run can fit how the parts have moved
    without reading an orientation."""
    import time
    added = added_copper(placed.copper, routed.copper)
    out = []
    for net in nets:
        new = [c for c in added if c.net == net]
        if not new:
            continue
        fps = [fp for fp in routed.footprints if any(p.net == net for p in fp.pads)]
        centres = {fp.ref: _pad_centres(fp) for fp in fps}
        pads = [(fp, p) for fp in fps for p in fp.pads if p.net == net]
        own = [c for c in placed.copper if c.net == net and c.outlines]
        ends = {}
        for c in new:
            for a in (c.anchors if c.kind == "track" else c.anchors[:1]):
                k = (round(_xy(a)[0], 4), round(_xy(a)[1], 4))
                ends[k] = ends.get(k, 0) + 1
        used = {}

        def point(xy):
            for fp, p in pads:                   # on a pad of its own net: that pad, where on it
                if any(point_in_polygon(xy, o) for o in p.outlines):
                    kind = "pad"
                    break
            else:
                kind = "anchor"
                fp, p = min(pads, key=lambda fp_p: math.dist(xy, _xy(centres[fp_p[0].ref][fp_p[1].number])))
            c = centres[fp.ref][p.number]
            used.setdefault(fp.ref, (fp, set()))[1].add(p.number)
            out = {kind: [fp.inst, p.number], "offset": [round(xy[0] - c.x, 6), round(xy[1] - c.y, 6)]}
            # a free end of the new copper that lay on the net's other copper: it must still, or it dangles
            if kind == "anchor" and ends.get((round(xy[0], 4), round(xy[1], 4)), 0) == 1 \
                    and any(point_in_polygon(xy, o) for c in own for o in c.outlines):
                out["meets"] = True
            return out
        tracks = tuple({"layer": next(iter(c.layers)).value, "width": c.width_mm,
                        "a": point(_xy(c.anchors[0])), "b": point(_xy(c.anchors[-1]))}
                       for c in new if c.kind == "track")
        vias = tuple({"at": point(_xy(c.anchors[0]) if c.anchors else (c.box.center.x, c.box.center.y)),
                      "size": round(c.box.width, 4), "drill": c.drill_mm}
                     for c in new if c.kind == "via")
        parts = {}
        for ref, (fp, numbers) in sorted(used.items()):
            keep = sorted(set(numbers) | set(_spread(centres[ref])))
            parts[fp.inst] = {"face": fp.face.value,
                          "pads": {n: [round(centres[ref][n].x, 6), round(centres[ref][n].y, 6)] for n in keep}}
        out.append(RouteEntry(net, tracks, vias, parts, time.strftime("%Y-%m-%d")))
    return out


def _fit(src: list, dst: list) -> tuple:
    """The turn (cos, sin) and the two centroids of the rigid motion taking
    the points `src` to `dst`, least squares, no mirror. With fewer than two
    distinct points there is no turn to see: none is assumed."""
    n = len(src)
    sx, sy = sum(p[0] for p in src) / n, sum(p[1] for p in src) / n
    dx, dy = sum(p[0] for p in dst) / n, sum(p[1] for p in dst) / n
    num = sum((a[0] - sx) * (b[1] - dy) - (a[1] - sy) * (b[0] - dx) for a, b in zip(src, dst))
    den = sum((a[0] - sx) * (b[0] - dx) + (a[1] - sy) * (b[1] - dy) for a, b in zip(src, dst))
    r = math.hypot(num, den)
    return ((den / r, num / r) if r > 1e-12 else (1.0, 0.0)), (sx, sy), (dx, dy)


def _pad_net(occ, ref, number):
    for s in occ.items[ref].shapes:
        if s.kind in ("pad", "through") and s.label == number:
            return s.net
    return None


def resolve(entry: RouteEntry, occ, tolerance: float):
    """(tracks, vias) where the entry's copper now lies, or why it cannot be
    drawn: a part it joins is gone or on the other face, a pad it binds to is
    gone or on another net, the parts have moved or turned relative to each
    other since it was adopted (by more than `tolerance`, mm at any of their
    kept pads), or an end that met the net's other copper no longer does."""
    from .lock import ref_of

    def label(name):                          # the instance a script names, and the refdes KiCad shows
        ref = ref_of(occ.geometry, name)
        return name if ref == name else "%s (%s)" % (name, ref)
    src, dst, whose = [], [], []
    for name in sorted(entry.parts):          # an instance path, or a refdes as 0.43-0.46 wrote it
        kept, ref = entry.parts[name], ref_of(occ.geometry, name)
        if ref not in occ.items:
            return "%s is no longer on the board" % label(name)
        if occ.items[ref].reference.face.value != kept["face"]:
            return "%s is on the other face now" % label(name)
        for number, at in sorted(kept["pads"].items()):
            try:
                now = occ.pad_location(ref, number)
            except KeyError:
                return "%s has no pad %s now" % (label(name), number)
            src.append(tuple(at))
            dst.append((now.x, now.y))
            whose.append(name)
    points = [t[e] for t in entry.tracks for e in ("a", "b")] + [v["at"] for v in entry.vias]
    for pt in points:
        if "pad" in pt:
            name, number = pt["pad"]
            net = _pad_net(occ, ref_of(occ.geometry, name), number)
            if net != entry.net:
                return "%s pad %s is on %s now" % (label(name), number, net or "no net")
    (c, s), (sx, sy), (dx, dy) = _fit(src, dst)

    def moved(p):
        x, y = p[0] - sx, p[1] - sy
        return (dx + c * x - s * y, dy + s * x + c * y)
    worst = max(range(len(src)), key=lambda i: math.dist(moved(src[i]), dst[i]))
    if math.dist(moved(src[worst]), dst[worst]) > tolerance:
        others = sorted(set(whose) - {whose[worst]})
        return "%s has moved or turned relative to %s since it was adopted" % (
            label(whose[worst]), ", ".join(map(label, others)) if others else "its own pads")

    def locate(pt):
        name, number = pt["pad"] if "pad" in pt else pt["anchor"]
        at = occ.pad_location(ref_of(occ.geometry, name), number)
        ox, oy = pt["offset"]
        return Location(round(at.x + c * ox - s * oy, 6), round(at.y + s * ox + c * oy, 6))
    copper = [o for o in occ.copper if o.net == entry.net]
    for pt in points:
        if pt.get("meets"):
            at = locate(pt)
            if not any(point_in_polygon((at.x, at.y), o.poly) for o in copper):
                return "its end at (%.2f, %.2f) no longer meets the net's other copper" % (at.x, at.y)
    tracks = [Track(entry.net, CopperLayer.of(t["layer"]), t["width"], locate(t["a"]), locate(t["b"]))
              for t in entry.tracks]
    vias = [Via(entry.net, locate(v["at"]), v["drill"], v["size"]) for v in entry.vias]
    return tracks, vias


def adopt(script, placed, routed, nets=None, still_open=(), shorted=(), skipped=None) -> list:
    """Adopt the router's new copper on `nets` (None: every net it added
    copper to) into the script's routes file, merged over what it held. A
    net still open or shorted after the route is left out: a net is adopted
    whole and clean. The entries written; `skipped`, when given, gets
    {net: why} for each net left out."""
    skipped = {} if skipped is None else skipped
    added = {c.net for c in added_copper(placed.copper, routed.copper) if c.net}
    for net in (sorted(added) if nets is None else nets):
        if net in shorted:
            skipped[net] = "the router shorted it"
        elif net in still_open:
            skipped[net] = "still %d open (a net is adopted whole)" % still_open[net]
        elif net not in added:
            skipped[net] = "the route added no copper to it (closed already, or no such net)"
    new = entries_from(placed, routed, [n for n in (sorted(added) if nets is None else nets) if n not in skipped])
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
