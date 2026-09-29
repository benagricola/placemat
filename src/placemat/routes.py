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
from .geometry import point_in_polygon, polys_overlap
from .values import Box, CopperLayer, Face, Location

FORMAT = 1


@dataclass(frozen=True)
class RouteEntry:
    net: str
    tracks: tuple                      # {"layer", "width", "a", "b"}: a and b are route points, each
                                       # {"pad": [ref, n], "offset"} on its net's pad or {"anchor": [ref, n], "offset"}
    vias: tuple                        # {"at", "size", "drill"}
    parts: dict = field(default_factory=dict)   # ref -> {"face", "pads": {number: [x, y]}} when adopted
    adopted: str = ""
    partial: bool = False              # some islands of a net the route left open: the net has other entries


def path_for(script) -> Path:
    script = Path(script)
    return script.with_name(script.stem + ".routes.json")


def read(path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [RouteEntry(e["net"], tuple(e["tracks"]), tuple(e["vias"]), dict(e.get("parts", {})), e.get("adopted", ""),
                       bool(e.get("partial", False)))
            for e in data.get("entries", [])]


def write(path, entries) -> None:
    doc = {"format": FORMAT, "entries": [asdict(e) for e in sorted(entries, key=lambda e: e.net)]}
    for e in doc["entries"]:
        e["tracks"], e["vias"] = list(e["tracks"]), list(e["vias"])
    Path(path).write_text(json.dumps(doc, indent=1) + "\n")


def merged(old, new, held=None) -> list:
    """`old` with the entries in `new` added. `held`, one flag an `old` entry,
    says which held on the board the route was given: an entry of a net in
    `new` that did not hold is replaced, one that held stays (its copper was
    on that board, so it is not in the new entry). Without `held`, a whole
    entry replaces its net's and a partial one is added beside them."""
    nets = {e.net for e in new}
    if held is None:
        whole = {e.net for e in new if not e.partial}
        out = [o for o in old if o.net not in whole]
    else:
        out = [o for o, h in zip(old, held) if o.net not in nets or h]
    return out + list(new)


def replaced(old, new, held=None) -> list:
    """The entries of `old` that merging `new` drops."""
    kept = merged(old, [], None) if not new else merged(old, new, held)
    return [o for o in old if not any(o is k for k in kept)]


def entry_keys(entries) -> list:
    """The key each entry is drawn and reported under: its net, and for a
    net's second and later entries "NET #n"."""
    keys, seen = [], set()
    for e in entries:
        key, n = e.net, 1
        while key in seen:
            n += 1
            key = "%s #%d" % (e.net, n)
        seen.add(key)
        keys.append(key)
    return keys


def held_of(entries, adopted: dict) -> list:
    """Which of `entries` a plan's `adopted` says held."""
    return [adopted.get(k) == "held" for k in entry_keys(entries)]


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


def islands(placed, routed, net) -> list:
    """The router's new copper on `net` in islands, each as (its copper, the
    separate pieces of the net it joins). A piece is what the board already
    connects: a pad of the net with whatever copper already there (the
    script's, a kept route's) reaches it, or the plane - a zone of the net,
    which a via of it inside the zone, or a track ending in it on its layer,
    reaches. An island is copper touching on a layer they share, or through
    a piece. Copper on no path between two things (a track with an end that
    meets nothing, a via touching one thing) is trimmed first; each trimmed
    run, and each island joining fewer than two pieces, is one island with
    no pieces, so the caller can count what it dropped."""
    from .geometry import poly_distance
    new = [c for c in added_copper(placed.copper, routed.copper) if c.net == net]
    fresh = {id(c) for c in new}
    pads = [(fp.ref, p) for fp in routed.footprints for p in fp.pads if p.net == net]
    zones = [(z, [Box.of_points(o) for o in z.outlines]) for z in routed.copper if z.kind == "zone" and z.net == net]
    there = [c for c in routed.copper if c.net == net and c.kind in ("track", "via", "poly") and id(c) not in fresh
             and c.outlines]
    nodes = [(c.layers, c.outlines, c.box) for c in new] + [(p.layers, p.outlines, p.box) for _, p in pads] + \
        [(c.layers, c.outlines, c.box) for c in there]
    n_new, first_there = len(new), len(new) + len(pads)
    near = {i: set() for i in range(len(nodes))}
    for i in list(range(n_new)) + list(range(first_there, len(nodes))):    # pad to pad: never copper
        for j in range(i + 1, len(nodes)) if i < n_new else list(range(n_new, first_there)) + \
                list(range(i + 1, len(nodes))):
            (la, oa, ba), (lb, ob, bb) = nodes[i], nodes[j]
            if la & lb and ba.overlaps(bb, gap=1e-6) and \
                    min(poly_distance(x, y) for x in oa for y in ob) <= 1e-6:
                near[i].add(j)
                near[j].add(i)

    def in_zone(pt, layers):
        return any(z.layers & layers and any(b.contains_point(Location(*pt)) and point_in_polygon(pt, o)
                                             for b, o in zip(boxes, z.outlines)) for z, boxes in zones)

    def reaches_plane(i):
        c = new[i] if i < n_new else there[i - first_there]
        if c.kind == "via":
            return in_zone(_xy(c.anchors[0]) if c.anchors else (c.box.center.x, c.box.center.y), c.layers)
        if c.kind == "track":
            return any(in_zone(_xy(a), c.layers) for a in (c.anchors[0], c.anchors[-1]))
        return False
    plane = {i for i in list(range(n_new)) + list(range(first_there, len(nodes))) if reaches_plane(i)}
    alive = set(range(n_new))

    def met(i, pt):
        c = new[i]
        return in_zone(pt, c.layers) or any(point_in_polygon(pt, o) for j in near[i] if j >= n_new or j in alive
                                            for o in nodes[j][1])

    def leads_nowhere(i):
        c = new[i]
        if c.kind == "track":           # an end that meets nothing
            return not all(met(i, _xy(a)) for a in (c.anchors[0], c.anchors[-1]))
        return c.kind == "via" and i not in plane and \
            len([j for j in near[i] if j in alive or j >= n_new]) <= 1
    trimmed = True
    while trimmed:
        trimmed = False
        for i in sorted(alive):
            if leads_nowhere(i):
                alive.discard(i)
                trimmed = True
    # the pieces the board already has: pads and the copper already there, joined as they touch; the plane one
    piece = {}
    for start in range(n_new, len(nodes)):
        if start in piece:
            continue
        stack = [start]
        while stack:
            k = stack.pop()
            if k in piece:
                continue
            piece[k] = "plane" if k in plane else start
            stack += [j for j in near[k] if j >= n_new and j not in piece]
    for k in [k for k in piece if k in plane]:
        root = piece[k]
        for m in [m for m, r in piece.items() if r == root]:
            piece[m] = "plane"
    seen, out = set(), []

    def flood(start, within):
        stack, copper, joined = [start], [], set()
        while stack:
            i = stack.pop()
            if i in seen:
                continue
            seen.add(i)
            copper.append(new[i])
            if i in plane:
                joined.add("plane")
            for j in near[i]:
                if j >= n_new:
                    joined.add(piece[j])
                elif j in within and j not in seen:
                    stack.append(j)
        return copper, joined
    for start in sorted(alive):
        if start not in seen:
            copper, joined = flood(start, alive)
            out.append((copper, joined if len(joined) >= 2 else set()))
    dead = set(range(n_new)) - alive
    for start in sorted(dead):
        if start not in seen:
            out.append((flood(start, dead)[0], set()))
    return out


def entries_from(placed, routed, nets, pick=None) -> list:
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
        if pick is not None and net in pick:
            new = [c for c in new if id(c) in pick[net]]
        if not new:
            continue
        fps = [fp for fp in routed.footprints if any(p.net == net for p in fp.pads)]
        centres = {fp.ref: _pad_centres(fp) for fp in fps}
        pads = [(fp, p) for fp in fps for p in fp.pads if p.net == net]
        # the net's other copper an end may rest on - not a zone: KiCad refills a zone round what is there,
        # and a run holds no fills, so an end on one has nothing to be checked against
        own = [c for c in placed.copper if c.net == net and c.outlines and c.kind != "zone"]
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
        out.append(RouteEntry(net, tracks, vias, parts, time.strftime("%Y-%m-%d"),
                              partial=pick is not None and net in pick))
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


def resolve(entry: RouteEntry, occ, tolerance: float, also=()):
    """(tracks, vias) where the entry's copper now lies, or why it cannot be
    drawn: a part it joins is gone or on the other face, a pad it binds to is
    gone or on another net, the parts have moved or turned relative to each
    other since it was adopted (by more than `tolerance`, mm at any of their
    kept pads), or an end that met the net's other copper no longer does."""
    insts = {fp.inst: fp.ref for fp in occ.geometry.footprints}

    def ref_of(_geometry, name):             # an instance path, or a refdes as 0.43-0.46 wrote it
        return insts.get(name, name)

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
    copper = [o for o in occ.copper if o.net == entry.net] + [o for o in also if o.net == entry.net]
    for pt in points:
        if pt.get("meets"):
            at = locate(pt)
            if not any(point_in_polygon((at.x, at.y), o.poly) for o in copper):
                return "its end at (%.2f, %.2f) no longer meets the net's other copper" % (at.x, at.y)
    tracks = [Track(entry.net, CopperLayer.of(t["layer"]), t["width"], locate(t["a"]), locate(t["b"]))
              for t in entry.tracks]
    vias = [Via(entry.net, locate(v["at"]), v["drill"], v["size"]) for v in entry.vias]
    return tracks, vias


def _kept_shape(op):
    """`op` (a resolved entry's Track or Via) as the `also` argument
    `resolve` reads: an entry whose end rests on another kept entry's own
    copper needs that one drawn first, exactly as `_draw_adopted` draws
    them onto a generated board."""
    from .occupancy import Shape
    if isinstance(op, Via):
        return Shape("", "through", frozenset((Face.FRONT, Face.BACK)), frozenset(CopperLayer),
                    op.net, op.polygon, op.box)
    faces = frozenset([op.layer.face]) if op.layer.face else frozenset()
    return Shape("", "copper", faces, frozenset([op.layer]), op.net, op.polygon, op.box)


def drawn_now(entries, geometry, tolerance: float) -> list:
    """The tracks and vias `entries` (kept routes) draw on `geometry` right
    now: the same round-by-round resolution `_draw_adopted` draws them onto
    a generated board, since an entry whose end rests on another kept
    entry's copper needs that one resolved first. An entry that no longer
    holds (see `resolve`) draws nothing."""
    from .occupancy import Occupancy
    if not entries:
        return []
    occ = Occupancy(geometry)
    drawn, left, out = [], list(range(len(entries))), []
    while left:
        also = [_kept_shape(op) for op in drawn]
        now = {i: resolve(entries[i], occ, tolerance, also) for i in left}
        held = [i for i in left if not isinstance(now[i], str)]
        if not held:
            break
        for i in held:
            ops = list(now[i][0]) + list(now[i][1])
            drawn += ops
            out += ops
        left = [i for i in left if i not in held]
    return out


def without_kept(geometry, entries, tolerance: float):
    """`geometry` with the copper `entries` currently draw taken out: the
    room a re-route would have (`occupancy --corridor --ignore-kept`). A
    board item is one of them when it is the same net and its outline
    overlaps a drawn op's - not an exact match, since a track written to
    KiCad and re-read differs from the one Python drew it as by a
    tessellation error far under a track's own width."""
    import dataclasses
    ops = drawn_now(entries, geometry, tolerance)
    if not ops:
        return geometry
    by_net: dict = {}
    for op in ops:
        by_net.setdefault(op.net, []).append(op)

    def is_kept(c) -> bool:
        if c.kind not in ("track", "via") or c.net not in by_net:
            return False
        return any(any(polys_overlap(op.polygon, o) for o in c.outlines) for op in by_net[c.net])
    return dataclasses.replace(geometry, copper=tuple(c for c in geometry.copper if not is_kept(c)))


def items_of(entries, board) -> set:
    """The keys of the items the script places that the entries' parts
    belong to: a part placed on its own, or the cell it is a member of."""
    from .board_geometry import members_of
    owner = {}
    for intent in board._placements():
        item = getattr(intent, "item", None)
        if item is None:
            continue
        for fp in members_of(item):
            owner.setdefault(fp.inst, intent.key)
    refs = {fp.ref: fp.inst for fp in board.geometry.footprints}
    return {owner[n] for e in entries for n in (refs.get(p, p) for p in e.parts) if n in owner}


def adoptable(placed, routed, nets=None, still_open=(), shorted=(), skipped=None, partial: bool = False,
              counts=None) -> list:
    """The entries `adopt` would write, and nothing written: `skipped`,
    when given, gets {net: why} for each net left out. With `partial`, a net
    still open keeps each island of its new copper that joins two of its
    pads, or a pad and a plane of it, as a partial entry."""
    skipped = {} if skipped is None else skipped
    added_copper_list = added_copper(placed.copper, routed.copper)
    added = {c.net for c in added_copper_list if c.net}
    pick = {}
    for net in (sorted(added) if nets is None else nets):
        if net in shorted:
            skipped[net] = "the router shorted it"
        elif net in still_open and partial:
            keep, tally = [], {"kept": 0, "joined": 0, "dropped": 0}
            for copper, joined in islands(placed, routed, net):
                if joined:
                    keep += copper
                    tally["kept"] += 1
                    tally["joined"] += len(joined)
                else:
                    tally["dropped"] += 1
            if counts is not None:
                counts[net] = tally
            if not keep:
                skipped[net] = "still %d open, and no island of it joins two of its pieces" % still_open[net]
            else:
                pick[net] = keep
        elif net in still_open:
            skipped[net] = "still %d open (a net is adopted whole; --partial keeps its closed islands)" % still_open[net]
        elif net not in added:
            skipped[net] = "the route added no copper to it (closed already, or no such net)"
    nets_kept = [n for n in (sorted(added) if nets is None else nets) if n not in skipped]
    return entries_from(placed, routed, nets_kept, pick={n: {id(c) for c in cs} for n, cs in pick.items()})


def island_line(net: str, tally: dict, still: int) -> str:
    """How much of an open net was kept, for the adopt line."""
    return "%s: %d island(s) kept, joining %d of its separate pieces; %d dropped (leading nowhere, or joining " \
           "nothing new); still %d open" % (net, tally["kept"], tally["joined"], tally["dropped"], still)


def keep(script, new, held=None) -> None:
    """Merge `new` into the script's routes file (`held`: see merged)."""
    if new:
        path = path_for(script)
        write(path, merged(read(path), new, held))


def adopt(script, placed, routed, nets=None, still_open=(), shorted=(), skipped=None) -> list:
    """Adopt the router's new copper on `nets` (None: every net it added
    copper to) into the script's routes file, merged over what it held. A
    net still open or shorted after the route is left out: a net is adopted
    whole and clean. The entries written; `skipped`, when given, gets
    {net: why} for each net left out."""
    new = adoptable(placed, routed, nets, still_open, shorted, skipped)
    keep(script, new)
    return new


def release(script, nets) -> list:
    """Drop `nets` from the script's routes file; the nets it did not hold."""
    path = path_for(script)
    old = read(path)
    held = {e.net for e in old}
    write(path, [e for e in old if e.net not in set(nets)])
    return [n for n in nets if n not in held]


def describe(entry: RouteEntry) -> str:
    return "%-20s %d track(s), %d via(s), joining %s, adopted %s%s" % (
        entry.net, len(entry.tracks), len(entry.vias), ", ".join(sorted(entry.parts)) or "-", entry.adopted or "-",
        ", partial" if entry.partial else "")


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
