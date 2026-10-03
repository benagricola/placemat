"""A VRML 2 model read by placemat itself, for a footprint whose model is a `.wrl` with no STEP beside it (KiCad's own export reads STEP
only). Standard library only.

VRML models are in units of 0.1 inch (a 0402 resistor's model measures about 0.394 by 0.201 raw), so every coordinate is multiplied by 2.54
to millimetres. They use KiCad's model axes, so the placement matrix of model_place.py applies to them as to a STEP model's mesh.

Read: `Transform` (translation, rotation, scale), `Group`, `Switch`, `Shape` with `Appearance`/`Material` (diffuseColor, transparency) and
`IndexedFaceSet` (coord, coordIndex, creaseAngle), `DEF` and `USE`. Polygons are fanned into triangles. Normals are smooth across edges
under the crease angle and split over it. Anything else (lines, points, textures, lights) is ignored."""
from __future__ import annotations

import math
import re
from array import array

from .model_mesh import Material, Mesh

UNIT_MM = 2.54                                   # VRML model units are 0.1 inch

_TOKEN = re.compile(r'"[^"]*"|[{}\[\]]|[^\s{}\[\],"]+')


class VrmlError(ValueError):
    pass


def _tokens(text: str) -> list:
    text = re.sub(r"#[^\n]*", "", text)
    return _TOKEN.findall(text)


class _Parser:
    def __init__(self, toks):
        self.t, self.i, self.defs = toks, 0, {}

    def value(self):
        t = self.t
        if self.i >= len(t):
            raise VrmlError("the file ends in the middle of a value")
        tok = t[self.i]
        if tok == "DEF":
            name = t[self.i + 1]
            self.i += 2
            v = self.value()
            self.defs[name] = v
            return v
        if tok == "USE":
            name = t[self.i + 1]
            self.i += 2
            if name not in self.defs:
                raise VrmlError("USE of %r before its DEF" % name)
            return self.defs[name]
        if tok == "[":
            self.i += 1
            out = []
            while self.i < len(t) and t[self.i] != "]":
                out.append(self.value())
            self.i += 1
            return out
        if self.i + 1 < len(t) and t[self.i + 1] == "{" and not _is_number(tok):
            return self.node()
        self.i += 1
        if tok.startswith('"'):
            return tok[1:-1]
        try:
            return float(tok)
        except ValueError:
            return tok

    def node(self):
        kind = self.t[self.i]
        self.i += 2                                   # the type and its brace
        fields = {}
        while self.i < len(self.t) and self.t[self.i] != "}":
            name = self.t[self.i]
            self.i += 1
            v = self.value()
            if isinstance(v, float):                  # a vector field (SFVec3f, SFColor, SFRotation) is its numbers one after another
                vec = [v]
                while self.i < len(self.t) and _is_number(self.t[self.i]):
                    vec.append(float(self.t[self.i]))
                    self.i += 1
                v = vec[0] if len(vec) == 1 else vec
            fields[name] = v
        if self.i >= len(self.t):
            raise VrmlError("a %s node is not closed" % kind)
        self.i += 1
        return (kind, fields)

    def file(self) -> list:
        out = []
        while self.i < len(self.t):
            out.append(self.value())
        return out


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- transforms: a 3x3 matrix and a translation
_ID = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _apply(m, p):
    return tuple(sum(m[i][k] * p[k] for k in range(3)) for i in range(3))


def _rotation(axis, angle):
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z)
    if n == 0:
        return _ID
    x, y, z = x / n, y / n, z / n
    c, s = math.cos(angle), math.sin(angle)
    t = 1 - c
    return ((t * x * x + c, t * x * y - s * z, t * x * z + s * y),
            (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
            (t * x * z - s * y, t * y * z + s * x, t * z * z + c))


def _floats(v, n, default):
    return tuple(v[:n]) if isinstance(v, list) and len(v) >= n and all(isinstance(x, float) for x in v[:n]) else default


# ---------------------------------------------------------------- shapes
class _Acc:
    """The meshes of every shape of one colour and opacity."""

    def __init__(self):
        self.mats: dict = {}

    def add(self, colour, opacity, pos, nor, idx):
        m = self.mats.get((colour, opacity))
        if m is None:
            m = self.mats[(colour, opacity)] = Material(colour, opacity, array("f"), array("f"), array("I"))
        base = len(m.positions) // 3
        m.positions.extend(pos)
        m.normals.extend(nor)
        m.indices.extend(base + i for i in idx)


def _colour(app):
    if not (isinstance(app, tuple) and app[0] == "Appearance"):
        return (204, 204, 204), 1.0
    mat = app[1].get("material")
    if not (isinstance(mat, tuple) and mat[0] == "Material"):
        return (204, 204, 204), 1.0
    c = _floats(mat[1].get("diffuseColor"), 3, (0.8, 0.8, 0.8)) if isinstance(mat[1].get("diffuseColor"), list) else (0.8, 0.8, 0.8)
    tr = mat[1].get("transparency", 0.0)
    return tuple(int(round(max(0.0, min(1.0, v)) * 255)) for v in c), round(1.0 - float(tr if isinstance(tr, float) else 0.0), 3)


def _faces(coord_index):
    face = []
    for v in coord_index:
        i = int(v)
        if i < 0:
            if len(face) >= 3:
                yield face
            face = []
        else:
            face.append(i)
    if len(face) >= 3:
        yield face


def _newell(pts):
    nx = ny = nz = 0.0
    for a, b in zip(pts, pts[1:] + pts[:1]):
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    n = math.sqrt(nx * nx + ny * ny + nz * nz)
    return (nx / n, ny / n, nz / n) if n > 1e-12 else None


def _shape(shape, rot, scale, move, acc):
    geo = shape[1].get("geometry")
    if not (isinstance(geo, tuple) and geo[0] == "IndexedFaceSet"):
        return
    g = geo[1]
    coord = g.get("coord")
    pts = coord[1].get("point") if isinstance(coord, tuple) else None
    if not pts:
        return
    P = [tuple(pts[i:i + 3]) for i in range(0, len(pts) - 2, 3)]
    P = [tuple(UNIT_MM * (a + b) for a, b in zip(_apply(rot, (p[0] * scale[0], p[1] * scale[1], p[2] * scale[2])), move)) for p in P]
    crease = g.get("creaseAngle", 0.0)
    cos_crease = math.cos(min(float(crease) if isinstance(crease, float) else 0.0, math.pi))
    faces = []
    for f in _faces(g.get("coordIndex") or []):
        if max(f) >= len(P):
            continue
        n = _newell([P[i] for i in f])
        if n is not None:
            faces.append((f, n))
    around: dict = {}
    for fi, (f, _) in enumerate(faces):
        for v in f:
            around.setdefault(v, []).append(fi)
    slot, pos, nor, idx = {}, array("f"), array("f"), array("I")

    def vertex(v, fi):
        n0 = faces[fi][1]
        sx = sy = sz = 0.0
        for gi in around[v]:
            n = faces[gi][1]
            if n[0] * n0[0] + n[1] * n0[1] + n[2] * n0[2] >= cos_crease - 1e-9:
                sx, sy, sz = sx + n[0], sy + n[1], sz + n[2]
        ln = math.sqrt(sx * sx + sy * sy + sz * sz) or 1.0
        n = (sx / ln, sy / ln, sz / ln)
        key = (v, round(n[0], 3), round(n[1], 3), round(n[2], 3))
        s = slot.get(key)
        if s is None:
            s = slot[key] = len(slot)
            pos.extend(P[v])
            nor.extend(n)
        return s

    for fi, (f, _) in enumerate(faces):
        a = vertex(f[0], fi)
        for k in range(1, len(f) - 1):
            idx.extend((a, vertex(f[k], fi), vertex(f[k + 1], fi)))
    if len(idx):
        colour, opacity = _colour(shape[1].get("appearance"))
        acc.add(colour, opacity, pos, nor, idx)


def _walk(node, rot, scale, move, acc):
    if isinstance(node, list):
        for n in node:
            _walk(n, rot, scale, move, acc)
        return
    if not isinstance(node, tuple):
        return
    kind, f = node
    if kind == "Shape":
        _shape(node, rot, scale, move, acc)
    elif kind == "Transform":
        t = _floats(f.get("translation"), 3, (0.0, 0.0, 0.0))
        s = _floats(f.get("scale"), 3, (1.0, 1.0, 1.0))
        r = _floats(f.get("rotation"), 4, (0.0, 0.0, 1.0, 0.0))
        # a point p goes to T(R(S p)): fold this node's turn and scale into the parent's, keeping the scale separate from the turn
        nrot = _mul(rot, _rotation(r[:3], r[3]))
        nscale = tuple(scale[i] * s[i] for i in range(3))
        nmove = tuple(a + b for a, b in zip(move, _apply(rot, tuple(t[i] * scale[i] for i in range(3)))))
        _walk(f.get("children"), nrot, nscale, nmove, acc)
    elif kind in ("Group", "Switch", "Collision", "Anchor"):
        _walk(f.get("children") or f.get("choice"), rot, scale, move, acc)


def read_vrml(text: str) -> Mesh:
    """A VRML 2 file's text as a Mesh in millimetres (the model frame)."""
    if not text.lstrip().startswith("#VRML") and "{" not in text:
        raise VrmlError("not a VRML file")
    parser = _Parser(_tokens(text))
    try:
        top = parser.file()
    except (IndexError, VrmlError) as e:
        raise VrmlError("the VRML file cannot be read: %s" % e) from None
    acc = _Acc()
    _walk(top, _ID, (1.0, 1.0, 1.0), (0.0, 0.0, 0.0), acc)
    if not acc.mats:
        raise VrmlError("the VRML file has no geometry this reader knows (IndexedFaceSet)")
    return Mesh(list(acc.mats.values()))
