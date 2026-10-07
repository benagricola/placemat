"""Helpers shared by the core's module fragments.

A fragment's frame is its content and the keep-in round it
(`board.rect(fit=True)`): the core stamps the frame as the cell's box. These
helpers read which way a part's pads face for a rotation, and draw the core's
planes over the frame.

Positions here are relative to the fragment's main part, which stands at the
fit frame's origin; only differences matter.
"""
from placemat import board, CopperLayer, Net, Part


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


def placed_size(part, pad, rotation):
    """(width, height) of a pad as the part stands."""
    w, h = size(board.pad(Part(part), pad).box)
    return (h, w) if rotation % 180 else (w, h)
