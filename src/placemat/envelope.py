"""What a footprint draws, against what its courtyard says it needs."""
from __future__ import annotations

from .values import Box

_ORDER = ("silk", "body", "mask", "copper")          # which layer is named when two set a side together


def _layers(fp) -> dict:
    boxes = {"silk": [Box.of_points(p) for _, p in fp.silk],
             "body": [Box.of_points(p) for _, p in fp.fab],
             "mask": [Box.of_points(p) for _, p in fp.mask],
             "copper": [p.box for p in fp.pads]}
    return {k: Box.union(v) for k, v in boxes.items() if v}


def drawn_envelope(fp):
    """The box round everything the part draws - pads, mask openings, silk
    and body - and, for each side, the layer that sets it."""
    layers = _layers(fp)
    if not layers:
        return None, {}
    box = Box.union(list(layers.values()))
    sides = {}
    for side, pick in (("left", lambda b: -b.left), ("top", lambda b: -b.top),
                       ("right", lambda b: b.right), ("bottom", lambda b: b.bottom)):
        far = max(pick(b) for b in layers.values())
        sides[side] = next(k for k in _ORDER if k in layers and abs(pick(layers[k]) - far) < 1e-9)
    return box, sides


def understatement(fp, clearance: float):
    """How far the footprint's silk or pads pass its courtyard, and which,
    when that is more than `clearance`; else None."""
    ct = fp.courtyard_box
    worst = None
    for kind, boxes in (("silk", [Box.of_points(p) for _, p in fp.silk]), ("pads", [p.box for p in fp.pads])):
        for b in boxes:
            over = max(ct.left - b.left, b.right - ct.right, ct.top - b.top, b.bottom - ct.bottom)
            if over > clearance + 1e-9 and (worst is None or over > worst[0] + 1e-9):
                worst = (round(over, 3), kind)
    return worst


def courtyard_findings(fp) -> list:
    """What is wrong with a footprint's courtyard as drawn: one that lies
    inside its own silk claims less than the part prints, and one that equals
    its fab body leaves no assembly margin round it."""
    out = []
    ct = fp.courtyard_box
    if fp.silk:
        silk = Box.union([Box.of_points(p) for _, p in fp.silk])
        if (silk.left <= ct.left + 1e-6 and silk.top <= ct.top + 1e-6
                and silk.right >= ct.right - 1e-6 and silk.bottom >= ct.bottom - 1e-6):
            out.append("courtyard lies inside its own silk")
    for _, poly in fp.fab:
        body = Box.of_points(poly)
        if all(abs(a - b) < 0.01 for a, b in zip((ct.left, ct.top, ct.right, ct.bottom),
                                                 (body.left, body.top, body.right, body.bottom))):
            out.append("courtyard equals its fab body: no assembly margin")
            break
    return out
