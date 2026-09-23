"""A plan drawn as SVG: what `placemat preview` shows without building the
board. Pure: the drawing is made from placemat's own model - the occupancy
after placement, the planned copper, the links, the congestion grid - and the
same plan gives the same text.

Each face asked for is a panel, the back mirrored as seen from the front, on a
millimetre grid; a column beside them carries the legend, the counts and the
parts that were not placed. Units are millimetres throughout (the viewBox);
whoever turns it into pixels chooses the size."""
from __future__ import annotations

from types import SimpleNamespace

from .board_geometry import members_of
from .copper import Pour, Text, Track, Via, Zone
from .geometry import circle_polygon
from .placement import Placement
from .values import Box, Face

MARGIN = 3.0            # mm round the board inside a panel
LEFT = 4.0              # mm left of the first panel, for its axis labels
HEAD = 5.5              # mm above the panels: the title and each panel's heading
FOOT = 3.0              # mm below the panels, for their axis labels
GAP = 6.0               # mm between panels
SIDE = 46.0             # mm of the column beside the panels
FONT = 0.9              # mm, a reference's text

_COLOUR = {"pad": "#e8a33d", "through": "#c9a227", "courtyard": "#c03cc0", "body": "#4a7fc1", "silk": "#222222",
           "keepout": "#f2b8c6", "reservation": "#b8d4f2", "track": "#c05050", "via": "#8a5a2b", "plane": "#d9a0a0",
           "ok": "#2f9e44", "over": "#e03131", "free": "#999999", "pocketed": "#f08c00", "board": "#333333"}


def _n(v: float) -> str:
    text = "%.3f" % v
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return "0" if text in ("-0", "") else text


def _points(poly) -> str:
    return " ".join("%s,%s" % (_n(x), _n(y)) for x, y in poly)


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


class _Panel:
    """One face: its shapes, and text that stays readable when mirrored."""

    def __init__(self, face: Face, mirrored: bool):
        self.face, self.mirrored, self.out = face, mirrored, []

    def add(self, line: str):
        self.out.append(line)

    def text(self, x: float, y: float, text: str, size: float = FONT, cls: str = "label", anchor: str = "middle",
             colour: str = "#1f3b73"):
        flip = ' transform="translate(%s %s) scale(-1 1)"' % (_n(x), _n(y)) if self.mirrored else ""
        at = ' x="0" y="0"' if self.mirrored else ' x="%s" y="%s"' % (_n(x), _n(y))
        self.add('<text class="%s"%s%s font-size="%s" text-anchor="%s" dominant-baseline="middle" fill="%s">%s</text>'
                 % (cls, at, flip, _n(size), anchor, colour, _esc(text)))


def _board_loops(plan) -> list:
    """The board's edge and its holes as polygons."""
    shape = plan.shape
    if shape is not None and hasattr(shape, "loops"):
        return [tuple(l) for l in shape.loops]
    if shape is not None and hasattr(shape, "polygon"):
        loops = [shape.polygon()]
        if getattr(shape, "bore", 0):
            loops.append(circle_polygon(shape.centre, shape.bore / 2.0))
        return loops + [tuple(l) for l in getattr(getattr(shape, "cutouts", None), "loops", ())]
    box = plan.outline or plan.occupancy.board_box
    if box is None:
        return []
    rect = ((box.left, box.top), (box.right, box.top), (box.right, box.bottom), (box.left, box.bottom))
    return [rect] + [tuple(l) for l in getattr(plan.cutouts, "loops", ())]


def _extent(plan) -> Box:
    boxes = [Box.of_points(l) for l in _board_loops(plan)]
    for s in plan.steps:
        if s.placement is not None and s.item in plan._items:
            for fp in members_of(plan._items[s.item]):
                g = plan.occupancy.items.get(fp.ref)
                if g is not None:
                    boxes.append(g.body)
    return Box.union(boxes) if boxes else Box(0, 0, 10, 10)


def _placed(plan) -> list:
    """(step, footprint) for every placed footprint, each once, in step order."""
    out, seen = [], set()
    for s in plan.steps:
        if s.placement is None or s.kind not in ("part", "cell") or s.item not in plan._items:
            continue
        for fp in members_of(plan._items[s.item]):
            if fp.ref not in seen and fp.ref in plan.occupancy.items:
                seen.add(fp.ref)
                out.append((s, fp))
    return out


def _drawn_at(plan, fp, polys):
    """A footprint's drawn polygons (silk, fab), moved from where the
    generator left it to where it now stands, with the face each is on."""
    occ = plan.occupancy
    geom = occ.items[fp.ref]
    t = occ._transform(SimpleNamespace(reference=Placement(fp.location, fp.rotation, fp.face)), geom.reference)
    flip = geom.reference.face != fp.face
    out = []
    for face, poly in polys:
        if flip:
            face = Face.BACK if face is Face.FRONT else Face.FRONT
        out.append((face, tuple(t.apply(p) for p in poly)))
    return out


def _heat(panel: _Panel, rudy):
    cell, o = rudy.cell, rudy.origin
    panel.add('<g class="heat">')
    for j, row in enumerate(rudy.util):
        for i, u in enumerate(row):
            if u <= 0.05:
                continue
            t = min(u, 1.5) / 1.5
            colour = "#%02x%02x%02x" % (255, int(240 * (1 - t) + 15), int(160 * (1 - t)))
            panel.add('<rect x="%s" y="%s" width="%s" height="%s" fill="%s" fill-opacity="%s"/>' % (
                _n(o.x + i * cell), _n(o.y + j * cell), _n(cell), _n(cell), colour, _n(0.25 + 0.4 * t)))
    panel.add("</g>")
    w = rudy.worst_at
    panel.add('<circle class="worst" cx="%s" cy="%s" r="%s" fill="none" stroke="#c92a2a" stroke-width="0.15"/>' % (
        _n(w.x), _n(w.y), _n(cell * 1.6)))
    panel.text(w.x, w.y - cell * 2.4, "worst %.2f" % rudy.worst, size=0.8, cls="worst-label", colour="#c92a2a")


def _grid(panel: _Panel, box: Box):
    panel.add('<g class="grid" stroke="#e6e6e6" stroke-width="0.05">')
    x = int(box.left // 5) * 5
    while x <= box.right:
        panel.add('<line x1="%s" y1="%s" x2="%s" y2="%s"/>' % (_n(x), _n(box.top), _n(x), _n(box.bottom)))
        x += 5
    y = int(box.top // 5) * 5
    while y <= box.bottom:
        panel.add('<line x1="%s" y1="%s" x2="%s" y2="%s"/>' % (_n(box.left), _n(y), _n(box.right), _n(y)))
        y += 5
    panel.add("</g>")
    x = int(box.left // 10) * 10
    while x <= box.right:
        panel.text(x, box.bottom + 1.2, str(x), size=0.9, cls="axis", colour="#888888")
        x += 10
    y = int(box.top // 10) * 10
    while y <= box.bottom:
        panel.text(box.left - 1.4, y, str(y), size=0.9, cls="axis", colour="#888888")
        y += 10


def _face_of(layer) -> Face | None:
    return getattr(layer, "face", None)


def _panel(plan, face: Face, mirrored: bool, box: Box, heat: bool, links: bool, copper: bool) -> list:
    """One face's drawing. `heat` is asked of the first panel only: congestion
    is one map for the board, and drawn twice it hides the second face."""
    occ = plan.occupancy
    p = _Panel(face, mirrored)
    p.add('<rect class="paper" x="%s" y="%s" width="%s" height="%s" fill="#ffffff"/>' % (
        _n(box.left), _n(box.top), _n(box.width), _n(box.height)))
    _grid(p, box)
    loops = _board_loops(plan)
    if loops:
        dash = '' if plan.draw_outline else ' stroke-dasharray="0.4 0.4"'
        p.add('<path class="board" d="%s" fill="#fbfaf5" fill-rule="evenodd" stroke="%s" stroke-width="0.15"%s/>' % (
            " ".join("M %s Z" % _points(l).replace(" ", " L ") for l in loops), _COLOUR["board"], dash))
    if heat and getattr(plan, "rudy", None) is not None and getattr(plan.rudy, "util", None):
        _heat(p, plan.rudy)
    for name in sorted(plan.keepouts):
        k = plan.keepouts[name]
        poly = getattr(k, "poly", None) or getattr(k, "polygon", None)
        if poly:
            p.add('<polygon class="keepout" points="%s" fill="%s" fill-opacity="0.45" stroke="#d6336c" stroke-width="0.08"/>'
                  % (_points(poly), _COLOUR["keepout"]))
            c = Box.of_points(poly).center
            p.text(c.x, c.y, name, size=0.8, cls="keepout-label", colour="#a61e4d")
    for r in occ.reservations:
        if r.layer is not None and _face_of(r.layer) not in (None, face):
            continue
        p.add('<polygon class="reservation" points="%s" fill="%s" fill-opacity="0.25" stroke="#4c6ef5" '
              'stroke-width="0.05" stroke-dasharray="0.3 0.3"/>' % (_points(r.poly), _COLOUR["reservation"]))
    if copper:
        p.add('<g class="copper">')
        for op in plan.copper:
            if isinstance(op, Track) and _face_of(op.layer) in (None, face):
                inner = _face_of(op.layer) is None
                p.add('<line class="track" x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="%s" '
                      'stroke-linecap="round"%s/>' % (_n(op.start.x), _n(op.start.y), _n(op.end.x), _n(op.end.y),
                                                     _COLOUR["track"], _n(op.width),
                                                     ' stroke-opacity="0.4"' if inner else ""))
            elif isinstance(op, Via):
                p.add('<circle class="via" cx="%s" cy="%s" r="%s" fill="%s" stroke="#ffffff" stroke-width="%s"/>' % (
                    _n(op.at.x), _n(op.at.y), _n(op.size / 2), _COLOUR["via"], _n(max(op.size - op.drill, 0.05) / 4)))
            elif isinstance(op, (Zone, Pour)) and _face_of(op.layer) in (None, face):
                p.add('<polygon class="plane" points="%s" fill="none" stroke="%s" stroke-width="0.1" '
                      'stroke-dasharray="0.6 0.3"/>' % (_points(op.points), _COLOUR["plane"]))
            elif isinstance(op, Text) and op.face is face:
                p.text(op.at.x, op.at.y, op.text, size=max(op.size, 0.6), cls="silk-text", colour=_COLOUR["silk"])
        p.add("</g>")
    pocketed = set(plan.pocketed)
    for step, fp in _placed(plan):
        g = occ.items[fp.ref]
        mine = [s for s in g.shapes if face in s.faces]
        if not any(s.kind == "courtyard" for s in mine) and not any(s.kind in ("pad", "through") for s in mine):
            for s in g.shapes:
                if s.kind == "courtyard":
                    p.add('<polygon class="other" points="%s" fill="none" stroke="#cccccc" stroke-width="0.05"/>'
                          % _points(s.poly))
            continue
        for s in mine:
            if s.kind == "courtyard":
                p.add('<polygon class="courtyard" points="%s" fill="none" stroke="%s" stroke-width="0.06" '
                      'stroke-dasharray="0.25 0.2"/>' % (_points(s.poly), _COLOUR["courtyard"]))
        for f, poly in _drawn_at(plan, fp, fp.fab):
            if f is face:
                p.add('<polygon class="body" points="%s" fill="none" stroke="%s" stroke-width="0.07"/>' % (
                    _points(poly), _COLOUR["body"]))
        for f, poly in _drawn_at(plan, fp, fp.silk):
            if f is face:
                p.add('<polygon class="silk" points="%s" fill="%s"/>' % (_points(poly), _COLOUR["silk"]))
        for s in mine:
            if s.kind in ("pad", "through"):
                cls = "pad through" if s.kind == "through" else "pad"
                p.add('<polygon class="%s" points="%s" fill="%s"/>' % (cls, _points(s.poly), _COLOUR[s.kind]))
        c = g.body.center
        if step.item in pocketed:
            b = g.body
            p.add('<rect class="pocketed" x="%s" y="%s" width="%s" height="%s" fill="none" stroke="%s" '
                  'stroke-width="0.12" stroke-dasharray="0.4 0.25"/>' % (_n(b.left - 0.3), _n(b.top - 0.3), _n(b.width + 0.6), _n(b.height + 0.6),
                                             _COLOUR["pocketed"]))
        p.text(c.x, c.y, fp.ref, cls="ref")
    if links:
        p.add('<g class="links">')
        for l in plan.links:
            try:
                a, b = occ.pad_location(*l.a), occ.pad_location(*l.b)
            except KeyError:
                continue
            if l.a[0] not in {fp.ref for _, fp in _placed(plan)} or l.b[0] not in {fp.ref for _, fp in _placed(plan)}:
                continue
            state = "free" if l.limit_mm is None else ("ok" if a.distance(b) <= l.limit_mm + 1e-9 else "over")
            p.add('<line class="link %s" x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" stroke-width="0.12" '
                  'stroke-dasharray="0.5 0.25"/>' % (state, _n(a.x), _n(a.y), _n(b.x), _n(b.y), _COLOUR[state]))
            if l.limit_mm is not None:
                p.text((a.x + b.x) / 2, (a.y + b.y) / 2 - 0.6, "%.1f/%.1f" % (a.distance(b), l.limit_mm),
                       size=0.7, cls="link-label", colour=_COLOUR[state])
        p.add("</g>")
    return p.out


def _side(plan, x: float, top: float) -> tuple:
    """The column beside the panels - counts, congestion, the parts not
    placed, the legend - and how tall it is."""
    out = []
    y = [top + 1.5]

    def line(text, cls="info", size=1.1, colour="#222222", step=1.8):
        out.append('<text class="%s" x="%s" y="%s" font-size="%s" fill="%s">%s</text>' % (
            cls, _n(x), _n(y[0]), _n(size), colour, _esc(text)))
        y[0] += step
    placed = sum(1 for s in plan.steps if s.placement is not None)          # counted as a run counts them
    line("placed %d, findings %d" % (placed, len(plan.findings)), size=1.3, step=2.0)
    r = getattr(plan, "rudy", None)
    if r is not None:
        line("congestion: worst cell %.2f at (%.1f, %.1f)" % (r.worst, r.worst_at.x, r.worst_at.y))
    if plan.cleanup:
        line("cleanup: %d moved, %d swapped" % (plan.cleanup.get("moves", 0), plan.cleanup.get("swaps", 0)))
    unplaced = [s for s in plan.steps if s.placement is None and s.kind in ("part", "cell", "block")]
    if unplaced:
        y[0] += 0.6
        line("not placed (%d)" % len(unplaced), cls="unplaced", size=1.2, colour="#c92a2a")
        for s in unplaced:
            why = s.note.split("UNPLACED", 1)[-1].lstrip(": ") if "UNPLACED" in s.note else s.note
            line("%s: %s" % (s.item, why[:70]), cls="unplaced", size=0.85, colour="#c92a2a", step=1.3)
    y[0] += 1.0
    for name, label in (("pad", "copper pad"), ("through", "through pad"), ("courtyard", "courtyard"),
                        ("body", "fab body"), ("silk", "silk"), ("keepout", "keepout"),
                        ("reservation", "reservation / label"), ("ok", "link within limit"),
                        ("over", "link over limit"), ("free", "link, no limit"), ("pocketed", "took a pocket"),
                        ("track", "track"), ("via", "via")):
        out.append('<rect x="%s" y="%s" width="1.6" height="1.0" fill="%s"/>' % (_n(x), _n(y[0] - 0.7), _COLOUR[name]))
        out.append('<text class="legend" x="%s" y="%s" font-size="1" fill="#222222">%s</text>' % (
            _n(x + 2.2), _n(y[0]), _esc(label)))
        y[0] += 1.5
    return out, y[0] - top


def draw(plan, faces=("front", "back"), heat: bool = True, links: bool = True, copper: bool = True,
         title: str = "", region: Box | None = None) -> str:
    """The plan as SVG text. `region`, a box in board millimetres, draws that
    part of each face alone, clipped: a close look at a crowded spot."""
    if region is None:
        box = _extent(plan)
        box = Box(box.left - MARGIN, box.top - MARGIN, box.right + MARGIN, box.bottom + MARGIN + 1.5)
    else:
        box = region
    panels = [Face(f) if not isinstance(f, Face) else f for f in faces]
    total_w = len(panels) * box.width + (len(panels) - 1) * GAP + GAP + SIDE
    # A close look is the region alone: the counts and the legend belong to the whole view.
    side, side_h = _side(plan, LEFT + len(panels) * (box.width + GAP), HEAD) if region is None else ([], 0.0)
    if region is not None:
        total_w -= GAP + SIDE
    total_w += LEFT
    total_h = HEAD + max(box.height, side_h) + FOOT
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s %s %s %s" width="%smm" height="%smm" '
           'font-family="DejaVu Sans, sans-serif">' % (_n(0), _n(0), _n(total_w), _n(total_h), _n(total_w), _n(total_h)),
           '<rect x="0" y="0" width="%s" height="%s" fill="#ffffff"/>' % (_n(total_w), _n(total_h))]
    if title:
        out.append('<text class="title" x="%s" y="1.8" font-size="1.4" fill="#222222">%s</text>' % (_n(LEFT), _esc(title)))
    for k, face in enumerate(panels):
        ox = LEFT + k * (box.width + GAP) - box.left
        oy = HEAD - box.top
        mirrored = face is Face.BACK
        if mirrored:
            transform = "translate(%s %s) scale(-1 1)" % (_n(ox + box.left + box.right), _n(oy))
        else:
            transform = "translate(%s %s)" % (_n(ox), _n(oy))
        heading = "front" if not mirrored else "back, seen from the front"
        out.append('<text class="heading" x="%s" y="4.3" font-size="1.2" fill="#222222">%s</text>' % (
            _n(LEFT + k * (box.width + GAP)), heading))
        out.append('<clipPath id="clip-%s"><rect x="%s" y="%s" width="%s" height="%s"/></clipPath>' % (
            face.value, _n(box.left), _n(box.top), _n(box.width), _n(box.height)))
        out.append('<g class="face %s" transform="%s">' % (face.value, transform))
        out.append('<g clip-path="url(#clip-%s)">' % face.value)
        out += _panel(plan, face, mirrored, box, heat and k == 0, links, copper)
        out.append("</g>")
        out.append("</g>")
    out += side
    out.append("</svg>")
    return "\n".join(out) + "\n"
