"""A finished explore as the studio shows it: the board of its best variant.

An explore's record (explore._write_record) keeps where each variant put the focused items, not a board. A newer explore also keeps
the best variant's own plan document (in BEST_DIR, under the record's name), which the studio shows as it is. For an older one, the studio takes the board the explore's
run wrote and moves the focused items on it from where that board has them to where the best variant put them:

`group_focus(doc, focus, at)` gathers a written board's footprints (board_doc: one item per footprint, keyed by its instance) into one
item per focused key, so each moves as one, as the plan placed it. `move_items(doc, moves, thickness)` moves items from one placement
to another with the transform the placer itself uses (occupancy._transform: a change of face mirrors about the vertical through the
item's place, then turns), their shapes and their 3D models' matrices with them. Items the explore did not focus stay as the run
placed them, and the board's copper stays where it was laid."""
from __future__ import annotations

import copy

from .geometry import Transform, Location

BEST_DIR = "best"           # beside the records: each record's best variant's plan document, under the record's own name


def _focus_of(key: str, focus: list) -> str | None:
    """The focused key an instance belongs to: itself, or the longest focused key it sits under."""
    best = None
    for f in focus:
        if (key == f or key.startswith(f + ".")) and (best is None or len(f) > len(best)):
            best = f
    return best


def group_focus(doc: dict, focus, at: dict) -> dict:
    """`doc` with the items of each focused key gathered into one item keyed by it, where its first footprint was; `at` is
    {key: [x, y, rotation, face]}, the placement the board has the key at. The original is left alone."""
    focus = sorted(focus)
    out, groups = [], {}
    for it in doc.get("items", ()):
        f = _focus_of(it["key"], focus)
        if f is None:
            out.append(it)
            continue
        g = groups.get(f)
        if g is None:
            g = groups[f] = dict(it, key=f, members=[])
            pl = at.get(f)
            if pl:
                g.update(at=[pl[0], pl[1]], rotation=pl[2], face=pl[3])
            out.append(g)
        g["members"] = g["members"] + list(it.get("members", ()))
    return dict(doc, items=out)


def _transform(a, b) -> Transform:
    """From placement `a` to placement `b` ([x, y, rotation, face] each): occupancy._transform with `a` as the reference."""
    t = Transform.translate(-a[0], -a[1])
    flip = a[3] != b[3]
    if flip:
        t = t.then(Transform.mirror_x(Location(0, 0)))
    t = t.then(Transform.rotate(b[2] + a[2] if flip else b[2] - a[2]))
    return t.then(Transform.translate(b[0], b[1]))


_SWAP = {"front": "back", "back": "front"}


def _swap_layer(name: str) -> str:
    return "B." + name[2:] if name.startswith("F.") else "F." + name[2:] if name.startswith("B.") else name


def _matrix(m: list, t: Transform, flip: bool, height: float) -> list:
    """A model's column-major matrix (model_place.placement: scene x the board's x, scene y the height, scene z the board's y), moved by `t`;
    turned over through the board when `flip`, as model_place does (`height` is the front plane plus the back plane)."""
    sy, oy = (-1.0, height) if flip else (1.0, 0.0)
    rows = [[t.a, 0.0, t.b, t.tx], [0.0, sy, 0.0, oy], [t.c, 0.0, t.d, t.ty], [0.0, 0.0, 0.0, 1.0]]
    out = [0.0] * 16
    for col in range(4):
        for r in range(4):
            out[col * 4 + r] = sum(rows[r][k] * m[col * 4 + k] for k in range(4))
    return out


def move_items(doc: dict, moves: dict, thickness: float) -> tuple:
    """`doc` with each item of `moves` ({key: (from, to)}, placements as [x, y, rotation, face]) moved, and the keys moved. An item
    with no placement on either side, or not in the document, stays. The original is left alone."""
    from . import model_place
    front, back = model_place.planes(thickness)
    out, moved = [], []
    for it in doc.get("items", ()):
        a, b = moves.get(it["key"], (None, None))
        if not a or not b:
            out.append(it)
            continue
        t, flip = _transform(a, b), a[3] != b[3]
        it = copy.deepcopy(it)
        for m in it.get("members", ()):
            for s in m.get("shapes", ()):
                s["poly"] = [list(t.apply((p[0], p[1]))) for p in s.get("poly", ())]
                if flip:
                    s["faces"] = [_SWAP.get(f, f) for f in s.get("faces", ())]
                    if "layers" in s:
                        s["layers"] = [_swap_layer(l) for l in s["layers"]]
            for e in m.get("models", ()) or ():
                if e.get("matrix"):
                    e["matrix"] = _matrix(e["matrix"], t, flip, front + back)
        it.update(at=[b[0], b[1]], rotation=b[2], face=b[3])
        out.append(it)
        moved.append(it["key"])
    return dict(doc, items=out), moved
