"""What placemat knows about a part, said out loud.

Everything here is already in the BoardGeometry; none of it was ever printed,
which is why nine entries in PLACEMAT_GAPS.md were answered by grepping a
.kicad_mod or loading pcbnew in a scratch script. Pure: the formatting is
pinned by tests that run without KiCad, and `cli.py` stays a dispatcher.
"""
from __future__ import annotations

from collections import Counter

from .board_geometry import part_height
from .geometry import distance_to_boundary, polys_overlap
from .ranking import pin_count
from .values import Box, CopperLayer


def _xy(p) -> list:
    return [round(p.x, 3), round(p.y, 3)]


def _wh(b: Box) -> list:
    return [round(b.width, 3), round(b.height, 3)]


def _ltrb(b: Box) -> list:
    return [round(b.left, 3), round(b.top, 3), round(b.right, 3), round(b.bottom, 3)]


def _box_poly(b: Box):
    return ((b.left, b.top), (b.right, b.top), (b.right, b.bottom), (b.left, b.bottom))


def nearest_edge(poly, geometry) -> float | None:
    """How near a polygon comes to the board's edge, counting its holes: a
    cutout's edge is a board edge. None when the geometry carries no outline
    polygon, because inventing one would be worse than saying nothing."""
    rings = getattr(geometry, "board_polygon", ()) or ()
    if not rings:
        return None
    return round(min(distance_to_boundary(tuple(poly), r) for r in rings), 3)


def pad_facts(fp, pad, geometry=None) -> dict:
    """One pad. `size` is the box round its copper outlines, never the anchor
    size: for a custom pad the anchor is not the copper."""
    if pad.through:
        attribute = "through"
    elif len(pad.layers) == 1:
        attribute = "smd %s" % ("front" if next(iter(pad.layers)) is CopperLayer.F else "back")
    else:
        attribute = "smd"
    names = getattr(geometry, "pin_names", None) or {}
    return {"number": pad.number, "pin": names.get(fp.ref, {}).get(pad.number), "net": pad.net, "at": _xy(pad.box.center),
            "size": _wh(pad.box), "through": pad.through, "attribute": attribute,
            "drill": round(pad.drill_mm, 3) if pad.through else None,
            "layers": sorted(l.value for l in pad.layers),
            "outline": [[[round(x, 4), round(y, 4)] for x, y in poly] for poly in pad.outlines],
            "custom": bool(getattr(pad, "custom", False)),
            "mask_paste": list(pad.mask_paste)}


def part_facts(fp, geometry=None) -> dict:
    out = {"instance": fp.inst, "ref": fp.ref, "value": fp.value, "cell": fp.cell,
           "face": fp.face.value, "rotation": fp.rotation, "origin": _xy(fp.location),
           "body": _wh(fp.body_box), "courtyard": _wh(fp.courtyard_box),
           "physical": _wh(fp.phys_box), "pins": pin_count(fp),
           "mm2": round(fp.courtyard_box.area, 3)}
    from .envelope import courtyard_findings, drawn_envelope
    env, sides = drawn_envelope(fp)
    out["boxes"] = {"body": _ltrb(fp.body_box), "courtyard": _ltrb(fp.courtyard_box),
                    "physical": _ltrb(fp.phys_box), "envelope": _ltrb(env if env is not None else fp.phys_box)}
    if env is not None:
        from .envelope import envelope_items
        out["envelope"] = _wh(env)
        out["envelope_set_by"] = sides
        out["envelope_items"] = envelope_items(fp)
    out["footprint_findings"] = courtyard_findings(fp)
    out["models"] = [{"file": path, "offset": list(off), "rotate": list(rot), "scale": list(scale)}
                     for path, off, rot, scale in getattr(fp, "models", ())]
    if fp.fab:
        out["boxes"]["fab"] = _ltrb(Box.union([Box.of_points(p) for _, p in fp.fab]))
    court = nearest_edge(_box_poly(fp.courtyard_box), geometry) if geometry is not None else None
    if court is not None:
        out["nearest_edge_courtyard"] = court
        copper = [q for p in fp.pads for o in p.outlines for q in o]
        if copper:
            out["nearest_edge_copper"] = nearest_edge(tuple(copper), geometry)
    return out


def copper_on(fp, geometry) -> dict:
    """The tracks and vias whose copper touches one of this part's pads, by
    kind. A count rather than a list, because the question this answers is
    "is anything wired to it" - what is AT a coordinate is the occupancy
    surface's question, not this one."""
    nets = {p.net for p in fp.pads if p.net}
    hits = {"track": 0, "via": 0}
    for c in geometry.copper:
        if c.kind not in hits or c.net not in nets:
            continue
        for p in fp.pads:
            if p.net != c.net or not c.box.overlaps(p.box):
                continue
            if any(polys_overlap(o, q) for o in c.outlines for q in p.outlines):
                hits[c.kind] += 1
                break
    return hits


def part_lines(fp, geometry=None, pads: bool = False, digest: str = "", envelope: bool = False) -> list:
    f = part_facts(fp, geometry)
    lines = ["part  %-24s %-6s %s" % (f["instance"], f["ref"], f["value"])]
    lines.append("  face %-6s rotation %-6g origin (%.2f, %.2f)%s" % (
        f["face"], f["rotation"], f["origin"][0], f["origin"][1],
        "  cell %s" % f["cell"] if f["cell"] else ""))
    lines.append("  body %.2f x %.2f   courtyard %.2f x %.2f   physical %.2f x %.2f" % (
        *f["body"], *f["courtyard"], *f["physical"]))
    from .envelope import drawn_envelope
    env, sides = drawn_envelope(fp)
    if env is not None:
        lines.append("  envelope %.2f x %.2f   set by %s" % (
            env.width, env.height, ", ".join("%s %s" % (k, sides[k]) for k in ("left", "top", "right", "bottom"))))
        if envelope:
            from .envelope import envelope_items
            for side, it in envelope_items(fp).items():
                lines.append("    %-6s %s %s  box %.2f %.2f %.2f %.2f" % (
                    side, it["layer"], "pad %s" % it["pad"] if "pad" in it else "%d of %d" % (it["index"], it["of"]),
                    *it["box"]))
    for path, off, rot, scale in getattr(fp, "models", ()):
        lines.append("  model %s  offset %.2f %.2f %.2f  rotate %g %g %g  scale %g %g %g" % (
            path.replace("\\", "/").rsplit("/", 1)[-1], *off, *rot, *scale))
    for finding in f["footprint_findings"]:
        lines.append("  footprint: %s" % finding)
    if "nearest_edge_courtyard" in f:
        lines.append("  nearest board edge: courtyard %.2f mm%s" % (
            f["nearest_edge_courtyard"],
            "" if f.get("nearest_edge_copper") is None else
            ", copper %.2f mm" % f["nearest_edge_copper"]))
    if digest:
        lines.append("  sha256 %s" % digest)
    if pads and geometry is not None and getattr(geometry, "copper", None):
        c = copper_on(fp, geometry)
        if c["track"] or c["via"]:
            lines.append("  copper on its pads: %d track(s), %d via(s)" % (c["track"], c["via"]))
    if pads:
        facts = [pad_facts(fp, p, geometry) for p in fp.pads]
        wheres = ["/".join(d["layers"]) if d["layers"] else d["attribute"] for d in facts]
        drills = ["drill %.2f" % d["drill"] if d["drill"] else "" for d in facts]
        # Laid out to this part's own widest entry, not to a constant: a
        # four-layer board names four layers on every through pad and a
        # two-layer board names two, so a fixed column moves the coordinates.
        wide = max([len(w) for w in wheres], default=0)
        deep = max([len(s) for s in drills], default=0)
        for d, where, drill in zip(facts, wheres, drills):
            column = "%-*s" % (wide, where) + ("  %-*s" % (deep, drill) if deep else "")
            lines.append("  pad %-5s %s%-14s %s  at (%.3f, %.3f)  %.3f x %.3f%s" % (
                d["number"], ("%-12s " % d["pin"]) if d["pin"] else "", d["net"] or "-", column,
                d["at"][0], d["at"][1], d["size"][0], d["size"][1],
                ("  " + "/".join(d["mask_paste"])) if d["mask_paste"] else ""))
            if d["custom"]:                     # its box hides its shape: an exposed pad's fingers
                for poly in d["outline"]:
                    lines.append("        outline %s" % " ".join("(%.3f, %.3f)" % (x, y) for x, y in poly))
    return lines


def _height_or_bad(fp):
    """A part's height, None when it has none, or its field's text when it is
    not a length: the listing is where a bad field is found, so it does not
    stop it."""
    try:
        return part_height(fp)
    except ValueError:
        return fp.fields.get("Pm.Height")


def parts_rows(geometry, fields=()) -> list:
    """One row per part; `fields` names footprint fields to add (an order
    code, a manufacturer part number), empty where a part has none."""
    return [{"instance": fp.inst, "ref": fp.ref, "face": fp.face.value, "cell": fp.cell,
             "x": fp.location.x, "y": fp.location.y, "rotation": fp.rotation,
             "centre": [round(fp.body_box.center.x, 3), round(fp.body_box.center.y, 3)],
             "mm2": round(fp.courtyard_box.area, 3), "pins": pin_count(fp),
             "value": fp.value, "footprint": fp.lib_id, "height": _height_or_bad(fp),
             "nets": sorted({p.net for p in fp.pads if p.net}),
             **({"fields": {f: fp.fields.get(f, "") for f in fields}} if fields else {})}
            for fp in sorted(geometry.footprints, key=lambda f: f.inst)]


def board_totals(geometry) -> dict:
    """The board's part and pad counts, and the solder joints an assembler
    places: the pads of every part it populates - a do-not-populate part and
    one on the board only (a fiducial, a mounting hole) left out."""
    fps = geometry.footprints
    return {"parts": len(fps), "pads": sum(len(fp.pads) for fp in fps),
            "joints": sum(len(fp.pads) for fp in fps if not fp.dnp and not fp.board_only)}


def parts_lines(geometry, fields=()) -> list:
    rows = parts_rows(geometry, fields)
    if not rows:
        return ["no footprints on this board"]
    out = ["%-26s %-6s %-6s %-12s %8s %8s %5s %8s %5s %6s  %-28s %s" % (
        "instance", "ref", "face", "cell", "x", "y", "rot", "mm2", "pins", "height", "value",
        "  ".join(["footprint"] + list(fields)))]
    for r in rows:
        extra = [r["footprint"] or "-"] + [r["fields"][f] or "-" for f in fields]
        out.append("%-26s %-6s %-6s %-12s %8.2f %8.2f %5g %8.2f %5d %6s  %-28s %s" % (
            r["instance"][:26], r["ref"], r["face"], (r["cell"] or "-")[:12],
            r["x"], r["y"], r["rotation"], r["mm2"], r["pins"],
            "-" if r["height"] is None else ("%.2f" % r["height"] if isinstance(r["height"], float) else "?"),
            r["value"][:28], "  ".join(extra)))
    t = board_totals(geometry)
    out.append("%d parts, %d pads, %d solder joints to assemble (do-not-populate and board-only parts left out)"
               % (t["parts"], t["pads"], t["joints"]))
    return out


def missing_order_number(fp, order_fields) -> bool:
    """A placed part carries no order number when none of `order_fields` (an
    order code, a manufacturer part number - `[parts] order_fields`) is
    present on it and non-empty. A part marked do-not-populate, left out of
    the BOM or on the board only (a mounting hole, a fiducial, a logo) is
    never missing one: it is never bought."""
    if fp.dnp or fp.bom_excluded or fp.board_only:
        return False
    return not any((fp.fields.get(f) or "").strip() for f in order_fields)


def order_warnings(geometry, order_fields) -> list:
    """One "no order number: REF (instance)" line per placed part missing
    one, instance order."""
    return ["no order number: %s (%s)" % (fp.ref, fp.inst)
            for fp in sorted(geometry.footprints, key=lambda f: f.inst) if missing_order_number(fp, order_fields)]


def pin_centres(pads) -> dict:
    """{pad number: its centre}, a pin drawn as several lands (an L-shaped
    corner pad, a split thermal land) measured as one: the centre of the box
    round its lands."""
    lands = {}
    for p in pads:
        lands.setdefault(p.number, []).append(p.box)
    return {n: Box.union(boxes).center for n, boxes in lands.items()}


def pitch_of(pads):
    """The nearest gap between two pins' centres: a part's pin pitch, the
    lands of one pin counting as that pin. None when there are not two pins
    to measure between."""
    centres = list(pin_centres(pads).values())
    if len(centres) < 2:
        return None
    return round(min(min(a.distance(b) for b in centres if b is not a) for a in centres), 6)


def pad_size_of(pads):
    """The commonest pad size: the one most pads share, which is what a land
    pattern is checked on. A pad or two of another size - a tab, a thermal
    pad - does not move it."""
    if not pads:
        return None
    sizes = Counter((round(p.box.width, 3), round(p.box.height, 3)) for p in pads)
    return sizes.most_common(1)[0][0]


def span_of(pads):
    """How far the copper reaches across every pad."""
    box = Box.union([p.box for p in pads]) if pads else None
    return round(box.width, 6) if box is not None else None


def _lands_on(pt, net, layers, geometry, own) -> str:
    """What a track's end lands on: a pad of its net (REF.NUMBER), a via, or
    another track of its net; '-' when nothing."""
    from .geometry import point_in_polygon
    for fp in geometry.footprints:
        for p in fp.pads:
            if p.net == net and p.layers & layers and any(point_in_polygon(pt, o) for o in p.outlines):
                return "%s.%s" % (fp.ref, p.number)
    for c in geometry.copper:
        if c.kind == "via" and c.net == net and any(point_in_polygon(pt, o) for o in c.outlines):
            return "via"
    for c in geometry.copper:
        if c is own or c.kind != "track" or c.net != net or not (c.layers & layers):
            continue
        if any(abs(pt[0] - a[0]) < 1e-3 and abs(pt[1] - a[1]) < 1e-3 for a in c.anchors):
            return "track"
    return "-"


def copper_segments(geometry, nets) -> list:
    """Every track segment on the board, of `nets` (every net when empty): its
    layer, width, ends, length, bearing (0-180 degrees from east, screen y
    down) and what each end lands on; `octilinear` when it runs at 0, 45 or
    90 degrees."""
    import math
    want = set(nets)
    out = []
    for c in geometry.copper:
        if c.kind != "track" or len(c.anchors) != 2 or (want and c.net not in want):
            continue
        (x1, y1), (x2, y2) = c.anchors
        chord = math.hypot(x2 - x1, y2 - y1)
        angle = round(math.degrees(math.atan2(-(y2 - y1), x2 - x1)) % 180.0, 2) if chord else 0.0
        arc = c.length_mm > chord + 1e-3
        out.append({"net": c.net, "layer": "/".join(sorted(l.value for l in c.layers)), "width": c.width_mm,
                    "start": [round(x1, 3), round(y1, 3)], "end": [round(x2, 3), round(y2, 3)],
                    "length": round(c.length_mm or chord, 3), "angle": angle, "arc": arc,
                    "octilinear": arc or min(abs(angle - a) for a in (0.0, 45.0, 90.0, 135.0, 180.0)) < 0.05,
                    "start_on": _lands_on((x1, y1), c.net, c.layers, geometry, c),
                    "end_on": _lands_on((x2, y2), c.net, c.layers, geometry, c)})
    out.sort(key=lambda s: (s["net"], s["layer"]))
    return out


def copper_lines(geometry, nets) -> list:
    lines = []
    for s in copper_segments(geometry, nets):
        lines.append("%s  %s  %.2f  (%.3f, %.3f) %s -> (%.3f, %.3f) %s  %.3f mm  %s%s" % (
            s["net"], s["layer"], s["width"], *s["start"], s["start_on"], *s["end"], s["end_on"], s["length"],
            "arc" if s["arc"] else "%.1f deg" % s["angle"], "" if s["octilinear"] else "  off 0/45/90"))
    want = set(nets)
    for c in geometry.copper:
        if c.kind == "via" and (not want or c.net in want):
            lines.append("%s  via  (%.3f, %.3f)  size %.2f drill %.2f" % (
                c.net, c.box.center.x, c.box.center.y, c.box.width, c.drill_mm))
    return lines or ["no tracks or vias%s" % (" on " + " ".join(nets) if nets else "")]


def _gap_to_region(poly, region) -> tuple:
    """(gap in mm, overlaps) from a part's polygon to a rule area: 0 and True
    when it reaches into the region, a hole of the region counting as outside."""
    from .geometry import distance_to_boundary, poly_distance, poly_within
    for hole in region.holes:
        if poly_within(poly, hole):
            return distance_to_boundary(poly, hole), False
    if polys_overlap(poly, region.polygon):
        return 0.0, True
    return poly_distance(poly, region.polygon), False


def keepout_clearances(geometry, names, near: float = 1.0) -> list:
    """Every part within `near` mm of a rule area (of `names`, or every one),
    on a face the area covers: its physical box's gap to the area and its
    courtyard's, and whether each reaches into it."""
    from .geometry import box_polygon
    want = set(names)
    rows = []
    for r in geometry.rule_areas:
        if want and r.name not in want:
            continue
        for fp in geometry.footprints:
            if r.layers and fp.face.copper not in r.layers:
                continue
            phys, pin = _gap_to_region(box_polygon(fp.phys_box), r)
            yard = fp.courtyard_poly or box_polygon(fp.courtyard_box)
            court, cin = _gap_to_region(yard, r)
            if min(phys, court) > near:
                continue
            rows.append({"keepout": r.name, "ref": fp.ref, "instance": fp.inst,
                         "physical": round(phys, 4), "physical_overlaps": pin,
                         "courtyard": round(court, 4), "courtyard_overlaps": cin})
    rows.sort(key=lambda row: (row["keepout"], row["physical"], row["courtyard"], row["ref"]))
    return rows


def keepout_lines(geometry, names, near: float = 1.0) -> list:
    def gap(v, inside):
        return "overlaps" if inside else "%.3f mm" % v
    lines, last = [], None
    for row in keepout_clearances(geometry, names, near):
        if row["keepout"] != last:
            area = next(r for r in geometry.rule_areas if r.name == row["keepout"])
            lines.append("%s (excludes %s):" % (row["keepout"], ", ".join(sorted(area.excludes)) or "nothing"))
            last = row["keepout"]
        lines.append("  %s (%s)  physical %s  courtyard %s" % (
            row["ref"], row["instance"], gap(row["physical"], row["physical_overlaps"]),
            gap(row["courtyard"], row["courtyard_overlaps"])))
    return lines or ["no part within %.2f mm of %s" % (near, " ".join(names) if names else "a keepout")]
