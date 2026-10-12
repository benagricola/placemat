"""Pad arithmetic shared by the core's module fragments.

A fragment's frame is its content and the keep-in round it
(`board.size(fit=True)`): the core stamps the frame as the cell's box. These
helpers say where a part's pads and drawn envelope land relative to another
part's pad, so a script can place its parts from the pads they serve.

Positions here are relative to the fragment's main part, which stands at the
fit frame's origin; only differences matter.
"""
import dataclasses

from placemat import board, CopperLayer, Net, Part, X


def size(box):
    """(width, height) of a box."""
    return box.right - box.left, box.bottom - box.top


def turn(dx, dy, rotation):
    """An offset turned as placemat turns a part: counter-clockwise as drawn,
    with y down, so a west pad goes south at 90."""
    return {0: (dx, dy), 90: (dy, -dx), 180: (-dx, -dy), 270: (-dy, dx)}[rotation % 360]


def pad_from_origin(part, pad, rotation=0):
    """The pad's centre from the part's origin, the part turned."""
    fp = board.part(Part(part))
    assert fp.rotation == 0, f"{part} is generated turned; its pad offsets would need that turn undone"
    c = board.pad(Part(part), pad).box.center
    return turn(c.x - fp.location.x, c.y - fp.location.y, rotation)


def inner_layers():
    """(signal, supply): In2 and In3, the core's signal layer and its 3V3
    plane. A cell stamped on the core's back keeps its inner copper on the
    layers it was drawn on, so a fragment draws on these on either face."""
    return CopperLayer.IN2, CopperLayer.IN3


def frame_planes(fillet, ground="GND", supply="V3V3", component_face=True):
    """The core's planes over the frame, inset by the keep-in so on a fit
    frame they cover the content and no more: ground on the component face (its minimum
    width rounds its corners at `fillet`; left out where the script zones
    that face itself), In1 and In4, and the 3V3 plane on In3."""
    k = board.keep_in
    if component_face:
        board.plane(Net(ground), layers=(CopperLayer.F,), inset=k, min_thickness=2.0 * fillet)
    board.plane(Net(ground), layers=(CopperLayer.IN1, CopperLayer.IN4), inset=k)
    if supply:
        board.plane(Net(supply), layers=(inner_layers()[1],), inset=k)


def shifted(v, d):
    """An X or Y reference (or a number) moved by d."""
    if isinstance(v, (int, float)):
        return v + d
    return dataclasses.replace(v, dx=v.dx + d) if isinstance(v, X) else dataclasses.replace(v, dy=v.dy + d)


def pour(net, corners, fillet, layer=CopperLayer.F):
    """Power copper of exactly this rectilinear outline: a pour, which does not
    pull back from other nets' copper, so the outline must clear foreign pads.
    `corners` are (x, y, ix, iy): a corner and the signs (+1 or -1) of the
    direction into the copper there. Drawn inset by the fillet and stroked at
    twice it, so the outline is unchanged and only the corners round."""
    pts = [(shifted(x, ix * fillet), shifted(y, iy * fillet)) for x, y, ix, iy in corners]
    board.pour(Net(net), pts, layer=layer, stroke=2.0 * fillet)


def pour_box(net, x0, y0, x1, y1, fillet, layer=CopperLayer.F):
    """`pour` of the box (x0, y0)-(x1, y1), x0 west and y0 north of x1, y1."""
    pour(net, [(x0, y0, 1, 1), (x1, y0, -1, 1), (x1, y1, -1, -1), (x0, y1, 1, -1)], fillet, layer)


class Content:
    """A group of parts laid out from one anchor part's pads.

    The anchor's origin is the group's origin. `beside()` places a part with
    one of its pads a given offset from a pad already in the group (a Pin
    placement from that PadRef) and remembers where its pads and body land,
    so later parts, and a second group, can be said relative to them.
    `place()` puts the anchor on the board: at the fit frame's origin for the
    fragment's main group, or offset from another group's anchor."""

    def __init__(self, anchor, rotation=0):
        self.anchor = anchor
        self.origins = {anchor: (0.0, 0.0)}
        self.rotations = {anchor: rotation}
        r = board.reach(Part(anchor), rotation=rotation)
        self.boxes = [(r.left, r.top, r.right, r.bottom)]

    def pad(self, part, pad):
        """Where a pad of a part in the group sits, in the group's coordinates."""
        ox, oy = self.origins[part]
        dx, dy = pad_from_origin(part, pad, self.rotations[part])
        return ox + dx, oy + dy

    def beside(self, part, pad, ref_part, ref_pad, dx, dy, rotation, why):
        """Place `part` so its `pad` is (dx, dy) from `ref_part`'s `ref_pad`."""
        from placemat import PadRef, Pin, X, Y
        rx, ry = self.pad(ref_part, ref_pad)
        ox, oy = pad_from_origin(part, pad, rotation)
        self.origins[part] = (rx + dx - ox, ry + dy - oy)
        self.rotations[part] = rotation
        r = board.reach(Part(part), rotation=rotation)
        x0, y0 = self.origins[part]
        self.boxes.append((x0 + r.left, y0 + r.top, x0 + r.right, y0 + r.bottom))
        ref = PadRef(Part(ref_part), ref_pad)
        board.place(Part(part), at=Pin(pad, X(ref, dx), Y(ref, dy)), rotation=rotation, why=why)

    @property
    def box(self):
        """(left, top, right, bottom) round the group's bodies."""
        return (min(b[0] for b in self.boxes), min(b[1] for b in self.boxes),
                max(b[2] for b in self.boxes), max(b[3] for b in self.boxes))

    def place(self, why, beside=None, dx=0.0, dy=0.0):
        """Put the anchor on the board: at the fit frame's origin, or with its
        origin (dx, dy) from `beside`'s anchor origin (another Content), said
        from that anchor's first pad."""
        from placemat import Location, PadRef, Pin, X, Y
        rotation = self.rotations[self.anchor]
        if beside is None:
            board.place(Part(self.anchor), at=Location(0, 0), rotation=rotation, why=why)
            return
        ref_pad = _first_pad(beside.anchor)
        rx, ry = beside.pad(beside.anchor, ref_pad)
        pad = _first_pad(self.anchor)
        px, py = pad_from_origin(self.anchor, pad, rotation)
        ref = PadRef(Part(beside.anchor), ref_pad)
        board.place(Part(self.anchor), at=Pin(pad, X(ref, dx + px - rx), Y(ref, dy + py - ry)), rotation=rotation, why=why)


def _first_pad(part):
    n = board.part(Part(part)).pads[0].number
    return int(n) if str(n).isdigit() else n


def drawn_from_pad(part, pad, rotation=0):
    """The part's drawn envelope (copper, mask and silk) relative to one of its
    pads' centre, the part turned: (left, top, right, bottom)."""
    from placemat.envelope import drawn_envelope
    fp = board.part(Part(part))
    env, _ = drawn_envelope(fp)
    corners = [turn(x - fp.location.x, y - fp.location.y, rotation)
               for x in (env.left, env.right) for y in (env.top, env.bottom)]
    px, py = pad_from_origin(part, pad, rotation)
    xs = [c[0] - px for c in corners]
    ys = [c[1] - py for c in corners]
    return min(xs), min(ys), max(xs), max(ys)


def placed_size(part, pad, rotation):
    """(width, height) of a pad as the part stands."""
    w, h = size(board.pad(Part(part), pad).box)
    return (h, w) if rotation % 180 else (w, h)
