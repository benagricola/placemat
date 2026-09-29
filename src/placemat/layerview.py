"""One copper layer of a board file, by net: its zone fills, zone outlines,
tracks, vias and pads, drawn with each net in its own colour, and each track
that runs inside another net's zone outline - the router routes round a
zone's last fill, not its outline, so such a track cuts the pour apart while
DRC passes, KiCad refilling round it."""
from __future__ import annotations

import colorsys

from .geometry import point_in_polygon, segments_intersect


def read_layer(pcb, layer: str) -> dict:
    """The layer's zones (net, outline, fills), tracks (net, ends, width),
    vias (net, centre, size) and pads (net, outline), read with pcbnew."""
    import pcbnew
    from .kicad.read import mm, outlines_of, quiet_stderr
    with quiet_stderr():
        board = pcbnew.LoadBoard(str(pcb))
    lid = board.GetLayerID(layer)
    if lid < 0 or not pcbnew.IsCopperLayer(lid):
        raise ValueError("%s has no copper layer %r" % (pcb, layer))
    zones = []
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea() or not z.IsOnLayer(lid):
            continue
        o = z.Outline()
        outline = [tuple((mm(o.Outline(k).CPoint(j).x), mm(o.Outline(k).CPoint(j).y))
                         for j in range(o.Outline(k).PointCount())) for k in range(o.OutlineCount())]
        fp = z.GetFilledPolysList(lid)
        fills = [tuple((mm(fp.Outline(k).CPoint(j).x), mm(fp.Outline(k).CPoint(j).y))
                       for j in range(fp.Outline(k).PointCount())) for k in range(fp.OutlineCount())]
        zones.append({"net": z.GetNetname(), "name": z.GetZoneName(), "outline": outline, "fills": fills})
    tracks, vias = [], []
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            if t.IsOnLayer(lid):
                c = t.GetPosition()
                vias.append({"net": t.GetNetname(), "at": (mm(c.x), mm(c.y)), "size": mm(t.GetWidth(lid))})
        elif t.GetLayer() == lid:
            s, e = t.GetStart(), t.GetEnd()
            tracks.append({"net": t.GetNetname(), "start": (mm(s.x), mm(s.y)), "end": (mm(e.x), mm(e.y)),
                           "width": mm(t.GetWidth())})
    pads = []
    for f in board.GetFootprints():
        for p in f.Pads():
            if p.IsOnLayer(lid):
                for poly in outlines_of(p, lid):
                    pads.append({"net": p.GetNetname(), "ref": "%s.%s" % (f.GetReference(), p.GetNumber()),
                                 "outline": poly})
    return {"layer": layer, "zones": zones, "tracks": tracks, "vias": vias, "pads": pads}


def _inside(a, b, poly) -> bool:
    if point_in_polygon(a, poly) or point_in_polygon(b, poly):
        return True
    return any(segments_intersect(a, b, poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))


def layer_crossings(items: dict) -> list:
    """Each track that runs inside, or across, a zone outline of another net
    on the layer."""
    out = []
    for t in items["tracks"]:
        for z in items["zones"]:
            if not z["net"] or z["net"] == t["net"]:
                continue
            if any(_inside(t["start"], t["end"], o) for o in z["outline"] if len(o) >= 3):
                out.append({"track_net": t["net"], "zone_net": z["net"], "zone": z["name"],
                            "start": [round(v, 3) for v in t["start"]], "end": [round(v, 3) for v in t["end"]]})
    return out


def net_colours(nets) -> dict:
    """A colour per net, spread round the hue circle in name order, so the same
    board draws the same way; no net is grey."""
    named = sorted(n for n in set(nets) if n)
    out = {"": "#888888"}
    for i, n in enumerate(named):
        r, g, b = colorsys.hsv_to_rgb((i * 0.618033988749895) % 1.0, 0.65, 0.85)
        out[n] = "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
    return out


def _pts(poly) -> str:
    return " ".join("%.3f,%.3f" % p for p in poly)


def layer_svg(items: dict, layer: str) -> str:
    """The layer as SVG in board millimetres: fills translucent, zone outlines
    dashed, pads, tracks and vias solid, a legend of the nets on the right."""
    nets = ([z["net"] for z in items["zones"]] + [t["net"] for t in items["tracks"]]
            + [v["net"] for v in items["vias"]] + [p["net"] for p in items["pads"]])
    colour = net_colours(nets)
    pts = ([p for z in items["zones"] for o in z["outline"] for p in o] + [t["start"] for t in items["tracks"]]
           + [t["end"] for t in items["tracks"]] + [v["at"] for v in items["vias"]]
           + [p for q in items["pads"] for p in q["outline"]])
    if not pts:
        x0 = y0 = 0.0
        x1 = y1 = 10.0
    else:
        x0, y0 = min(p[0] for p in pts) - 2.0, min(p[1] for p in pts) - 2.0
        x1, y1 = max(p[0] for p in pts) + 2.0, max(p[1] for p in pts) + 2.0
    legend = sorted(n for n in set(nets) if n)
    lw = 30.0
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="%.3f %.3f %.3f %.3f" width="%.0fmm" height="%.0fmm">'
           % (x0, y0, x1 - x0 + lw, y1 - y0, x1 - x0 + lw, y1 - y0),
           '<rect x="%.3f" y="%.3f" width="%.3f" height="%.3f" fill="#ffffff"/>' % (x0, y0, x1 - x0 + lw, y1 - y0),
           '<text x="%.3f" y="%.3f" font-size="1.2" font-family="sans-serif">%s</text>' % (x0 + 0.5, y0 + 1.5, layer)]
    for z in items["zones"]:
        c = colour.get(z["net"], "#888888")
        for f in z["fills"]:
            out.append('<polygon class="fill" points="%s" fill="%s" fill-opacity="0.45" stroke="none"/>' % (_pts(f), c))
        for o in z["outline"]:
            out.append('<polygon class="outline" points="%s" fill="none" stroke="%s" stroke-width="0.1" '
                       'stroke-dasharray="0.6 0.3"/>' % (_pts(o), c))
    for p in items["pads"]:
        out.append('<polygon class="pad" points="%s" fill="%s"/>' % (_pts(p["outline"]), colour.get(p["net"], "#888888")))
    for t in items["tracks"]:
        out.append('<line class="track" x1="%.3f" y1="%.3f" x2="%.3f" y2="%.3f" stroke="%s" stroke-width="%.3f" '
                   'stroke-linecap="round"/>' % (*t["start"], *t["end"], colour.get(t["net"], "#888888"), t["width"]))
    for v in items["vias"]:
        out.append('<circle class="via" cx="%.3f" cy="%.3f" r="%.3f" fill="%s" stroke="#ffffff" stroke-width="0.05"/>'
                   % (*v["at"], v["size"] / 2.0, colour.get(v["net"], "#888888")))
    lx = x1 + 1.0
    for i, n in enumerate(legend):
        y = y0 + 3.0 + i * 1.6
        out.append('<rect x="%.3f" y="%.3f" width="1.2" height="1.2" fill="%s"/>' % (lx, y - 1.0, colour[n]))
        out.append('<text x="%.3f" y="%.3f" font-size="1.0" font-family="sans-serif">%s</text>'
                   % (lx + 1.6, y, n.replace("&", "&amp;").replace("<", "&lt;")))
    out.append("</svg>")
    return "\n".join(out)
