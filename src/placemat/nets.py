"""What placemat knows about a net, said out loud: how many pads it has and
which parts it joins, how far it has to reach (span, the minimum spanning
tree over its pads' centres), how much copper is already down for it
(routed) and how that compares to its span (detour), its via count, the
copper layers its tracks use, and whether a pour serves it instead of the
router. Pure: no KiCad, so the formatting is pinned by tests that run
without it; `cli.py` asks `kicad.route.plane_nets_of` (which does need
KiCad) for the pour nets and passes them in.
"""
from __future__ import annotations

import math

from .board_geometry import stackup_order
from .ratsnest import Anchor, mst
from .values import Box

COLUMNS = ("net", "pads", "parts", "span", "routed", "detour", "vias", "layers", "pour")


def _span(net: str, anchors) -> float:
    edges = mst(net, anchors)
    return round(sum(math.hypot(e.a.x - e.b.x, e.a.y - e.b.y) for e in edges), 6)


def nets_rows(geometry, planes=frozenset(), inst: bool = False) -> list:
    """One row per net with at least two pads. `planes` names the pour nets
    (`kicad.route.plane_nets_of`); `inst` gives each net's parts as instance
    paths rather than refs."""
    by_net: dict = {}
    lands: dict = {}                     # a pin drawn as several lands is one pin, at the centre of their box
    for fp in geometry.footprints:
        for p in fp.pads:
            if p.net:
                key = (fp.ref, p.number)
                if key not in lands:
                    by_net.setdefault(p.net, []).append((fp, p))
                lands.setdefault(key, []).append(p.box)
    rows = []
    for net, items in sorted(by_net.items()):
        if len(items) < 2:
            continue
        anchors = []
        for fp, p in items:
            c = Box.union(lands[(fp.ref, p.number)]).center
            anchors.append(Anchor(fp.ref, p.number, c.x, c.y))
        span = _span(net, anchors)
        tracks = [c for c in geometry.copper if c.kind == "track" and c.net == net]
        routed = round(sum(c.length_mm for c in tracks), 6)
        vias = sum(1 for c in geometry.copper if c.kind == "via" and c.net == net)
        layers = sorted({l for c in tracks for l in c.layers}, key=stackup_order)
        parts = sorted({fp.inst if inst else fp.ref for fp, _ in items})
        rows.append({
            "net": net, "pads": len(items), "parts": parts, "span": span, "routed": routed,
            "detour": round(routed / span, 3) if routed > 0 and span > 0 else None,
            "vias": vias, "layers": [l.value for l in layers], "pour": net in planes,
        })
    return rows


def sort_rows(rows: list, column: str) -> list:
    """`rows` by `column`, largest first - the default order the span
    itself is given in - or, for `net`, A to Z. A list-valued column
    (parts, layers) sorts by how many; an unrouted net's `None` detour
    sorts last."""
    if column not in COLUMNS:
        raise ValueError("--sort takes one of %s, not %r" % (", ".join(COLUMNS), column))
    if column == "net":
        return sorted(rows, key=lambda r: r["net"])

    def key(r):
        v = r[column]
        if isinstance(v, (list, tuple)):
            return len(v)
        if v is None:
            return -1
        return v
    return sorted(rows, key=key, reverse=True)


def nets_lines(rows: list) -> list:
    if not rows:
        return ["no net on this board joins two or more pads"]
    out = ["%-20s %5s %-30s %9s %9s %7s %5s %-16s %s" % (
        "net", "pads", "parts", "span", "routed", "detour", "vias", "layers", "pour")]
    for r in rows:
        out.append("%-20s %5d %-30s %9.3f %9.3f %7s %5d %-16s %s" % (
            r["net"][:20], r["pads"], ", ".join(r["parts"])[:30] or "-", r["span"], r["routed"],
            "-" if r["detour"] is None else "%.2f" % r["detour"], r["vias"],
            "/".join(r["layers"])[:16] or "-", "yes" if r["pour"] else "-"))
    return out
