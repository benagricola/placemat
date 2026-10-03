"""Where a 3D model stands on the board, composed once, here: the matrix from a model's own frame to the viewer's scene frame.

The chain is KiCad's, measured against `kicad-cli pcb export glb` (docs/superpowers/specs/2026-10-03-studio-3d-design.md, "Placement"):

A. the model on the footprint as the generator left it. For a model-frame point v: scale, turn about x then y then z by the angles
   negated, then offset (`describe._model_xy` has the same order); onto the footprint's page (y down) as (x, -y) on the front and (x, y)
   on the back; turned by the footprint's orientation; moved to its location. Height above the part's own face is the model's z.
B. the plan moves the part. The plan's transform (`occupancy._transform`: the one that moves its pads and courtyard) moves the model's x and
   y too, and when the face changes the height flips about the board, so the model and its pads move together by construction.

Scene frame (glTF's, and KiCad's export's): x = board x, y = up, z = board y (down the page), millimetres, the board body from 0 to its
thickness T. The model planes (the height of a part's own face): front T - 0.005 and back -0.085, as the exporter puts them (measured on
KiCad 10.0.6; the converter's self-test checks them again at start-up, in model_convert.py).

Everything here is affine, so the matrix is read off the chain: where it sends the origin and the three unit vectors."""
from __future__ import annotations

import math
import re
from pathlib import Path

FRONT_BELOW = 0.005          # the front plane is this far under the board's top face (KiCad 10.0.6's glb export: T - 0.005)
BACK_PLANE = -0.085          # the back plane (the same export), for any thickness
DEFAULT_THICKNESS = 1.6      # KiCad's default board thickness, mm


def planes(thickness: float) -> tuple:
    """(front plane, back plane): the height a front part's own face and a back part's own face stand at."""
    return thickness - FRONT_BELOW, BACK_PLANE


def board_thickness(pcb_path) -> float:
    """The board's thickness in mm from the file's `(general (thickness ...))`; 1.6 when it says nothing or cannot be read."""
    try:
        with open(pcb_path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(65536)
    except OSError:
        return DEFAULT_THICKNESS
    m = re.search(r"\(general\s*\(thickness\s+([-\d.eE]+)\)", head)
    try:
        return float(m.group(1)) if m else DEFAULT_THICKNESS
    except ValueError:
        return DEFAULT_THICKNESS


def _turn(v, axis: str, deg: float):
    """`v` turned about an axis by `-deg` (KiCad's model rotation is applied negated, in its y-up frame)."""
    a = math.radians(-deg)
    c, s = math.cos(a), math.sin(a)
    x, y, z = v
    if axis == "x":
        return (x, y * c - z * s, y * s + z * c)
    if axis == "y":
        return (x * c + z * s, y, -x * s + z * c)
    return (x * c - y * s, x * s + y * c, z)


def _chain(v, entry, location, rotation, back: bool, to, flipped: bool, thickness: float):
    """One model-frame point to the scene frame."""
    off, rot, scale = entry[1], entry[2], entry[3]
    p = (v[0] * scale[0], v[1] * scale[1], v[2] * scale[2])
    p = _turn(_turn(_turn(p, "x", rot[0]), "y", rot[1]), "z", rot[2])
    p = (p[0] + off[0], p[1] + off[1], p[2] + off[2])
    qx, qy = (p[0], p[1]) if back else (p[0], -p[1])                      # the footprint's page: y down
    th = math.radians(rotation)
    c, s = math.cos(th), math.sin(th)
    x, y = qx * c + qy * s + location[0], -qx * s + qy * c + location[1]
    front_plane, back_plane = planes(thickness)
    z = back_plane - p[2] if back else front_plane + p[2]
    if to is not None:
        x, y = to.apply((x, y))
    if flipped:
        z = front_plane + back_plane - z
    return (x, z, y)


def placement(entry, *, location, rotation: float, face: str, to=None, flipped: bool = False, thickness: float = DEFAULT_THICKNESS) -> list:
    """The 4x4 matrix, column-major (three.js's order), from the model frame to the scene frame.

    `entry` is a footprint's model entry (file, offset, rotation, scale, ...); `location`, `rotation` and `face` (`"front"` or `"back"`) are
    the footprint's pose as the generator left it; `to` is the plan's transform (geometry.Transform, from that pose to where the plan put the
    part) and `flipped` whether the plan changed the face."""
    back = face == "back"
    args = (entry, location, rotation, back, to, flipped, thickness)
    o = _chain((0.0, 0.0, 0.0), *args)
    cols = []
    for e in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        p = _chain(e, *args)
        cols.append(tuple(p[i] - o[i] for i in range(3)))
    out = []
    for c in cols:
        out += [_clean(v, 6) for v in c] + [0.0]
    out += [_clean(v, 4) for v in o] + [1.0]
    return out


def _clean(v: float, digits: int) -> float:
    r = round(v, digits)
    return 0.0 if r == 0 else r
