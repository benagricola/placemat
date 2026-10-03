"""A 3D model as the viewer draws it: the `.pmm` mesh file, and the simplification that keeps a mesh under a triangle cap.

A mesh is a few materials (a colour, an opacity), each with positions, normals and triangle indices, in the model frame: x right, y up the
footprint's page, z up out of the board, millimetres (see model_place.py). The file is placemat's own, small enough for a page to read
with typed arrays, and not GLB, which only the converter has to read (model_convert.py).

File: the magic `PMMESH` and a little-endian u16 version, a u32 header length, the header (JSON, padded with spaces to a multiple of 4),
then per material the positions (float32 x3), the normals (float32 x3) and the indices (uint16 under 65536 vertices, else uint32), each
block padded to 4 bytes. The header has `converter` (the converter version that made it), `bbox` (x0 y0 z0 x1 y1 z1), `tris_in` and
`tris` (before and after simplification) and, per material, `colour` (sRGB 0..255), `opacity`, `nv`, `ni` and `index_bytes`."""
from __future__ import annotations

import json
import math
import struct
import sys
from array import array
from dataclasses import dataclass, field

CONVERTER_VERSION = 1
MAGIC = b"PMMESH"
FORMAT = 1


class MeshError(ValueError):
    """A file that is not a mesh of this format, or is cut short."""


@dataclass
class Material:
    colour: tuple                                  # sRGB, 0..255
    opacity: float
    positions: array                               # float32 x3 per vertex
    normals: array                                 # float32 x3 per vertex
    indices: array                                 # three per triangle


@dataclass
class Mesh:
    materials: list = field(default_factory=list)
    tris_in: int | None = None                     # the triangles before simplification, when it happened
    header: dict = field(default_factory=dict)     # as read from a file


def triangles(mesh: Mesh) -> int:
    return sum(len(m.indices) // 3 for m in mesh.materials)


def bbox(mesh: Mesh) -> list:
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for m in mesh.materials:
        p = m.positions
        for k in range(3):
            if len(p) > k:
                col = p[k::3]
                lo[k], hi[k] = min(lo[k], min(col)), max(hi[k], max(col))
    if lo[0] == math.inf:
        return [0.0] * 6
    return [round(v, 5) for v in lo + hi]


def _pad(n: int) -> int:
    return (-n) % 4


def _le(a: array) -> bytes:
    if sys.byteorder == "big":
        a = array(a.typecode, a)
        a.byteswap()
    return a.tobytes()


def write_pmm(mesh: Mesh) -> bytes:
    mats = []
    for m in mesh.materials:
        nv = len(m.positions) // 3
        mats.append({"colour": [int(c) for c in m.colour], "opacity": round(float(m.opacity), 3), "nv": nv, "ni": len(m.indices),
                     "index_bytes": 2 if nv < 65536 else 4})
    tris = triangles(mesh)
    header = {"version": FORMAT, "converter": CONVERTER_VERSION, "bbox": bbox(mesh), "tris_in": tris if mesh.tris_in is None else mesh.tris_in,
              "tris": tris, "materials": mats}
    h = json.dumps(header, separators=(",", ":")).encode()
    h += b" " * _pad(len(h))
    out = [MAGIC, struct.pack("<H", FORMAT), struct.pack("<I", len(h)), h]
    for m, meta in zip(mesh.materials, mats):
        out.append(_le(array("f", m.positions)))
        out.append(_le(array("f", m.normals)))
        idx = _le(array("H" if meta["index_bytes"] == 2 else "I", m.indices))
        out.append(idx + b"\0" * _pad(len(idx)))
    return b"".join(out)


def read_pmm(data: bytes) -> Mesh:
    if len(data) < 12 or data[:6] != MAGIC:
        raise MeshError("not a placemat mesh")
    (version,) = struct.unpack_from("<H", data, 6)
    if version != FORMAT:
        raise MeshError("a mesh of format %d" % version)
    (hl,) = struct.unpack_from("<I", data, 8)
    if 12 + hl > len(data):
        raise MeshError("the mesh file is cut short")
    try:
        header = json.loads(data[12:12 + hl].decode())
    except ValueError as e:
        raise MeshError("the mesh header is unreadable: %s" % e) from None
    at, mats = 12 + hl, []
    for meta in header["materials"]:
        nv, ni, ib = meta["nv"], meta["ni"], meta["index_bytes"]
        arrays = []
        for code, count in (("f", 3 * nv), ("f", 3 * nv), ("H" if ib == 2 else "I", ni)):
            a = array(code)
            size = a.itemsize * count
            if at + size > len(data):
                raise MeshError("the mesh file is cut short")
            a.frombytes(data[at:at + size])
            if sys.byteorder == "big":
                a.byteswap()
            at += size + (_pad(size) if code != "f" else 0)
            arrays.append(a)
        mats.append(Material(tuple(meta["colour"]), meta["opacity"], arrays[0], arrays[1], array("I", arrays[2])))
    return Mesh(mats, header.get("tris_in"), header)


def decimate(mesh: Mesh, max_tris: int):
    """(the mesh under `max_tris` triangles, the grid cell used in mm; 0 when it was already small enough). Vertex clustering: vertices in
    the same cell of a grid become one at their mean, a triangle with two corners in one cell goes. The grid grows until it fits; the
    box moves by at most a cell."""
    total = triangles(mesh)
    if total <= max_tris:
        return mesh, 0.0
    lo, hi = bbox(mesh)[:3], bbox(mesh)[3:]
    extent = max(hi[k] - lo[k] for k in range(3)) or 1.0
    cell = extent / max(8.0, math.sqrt(max_tris))
    while True:
        out = _cluster(mesh, lo, cell)
        if triangles(out) <= max_tris:
            out.tris_in = total if mesh.tris_in is None else mesh.tris_in
            return out, cell
        cell *= 1.25


def _cluster(mesh: Mesh, lo, cell: float) -> Mesh:
    mats = []
    for m in mesh.materials:
        pos, nor = m.positions, m.normals
        nv = len(pos) // 3
        key_of, slot, sums, counts, nsum = [0] * nv, {}, [], [], []
        for v in range(nv):
            k = (int((pos[3 * v] - lo[0]) / cell), int((pos[3 * v + 1] - lo[1]) / cell), int((pos[3 * v + 2] - lo[2]) / cell))
            s = slot.get(k)
            if s is None:
                s = slot[k] = len(sums)
                sums.append([0.0, 0.0, 0.0])
                nsum.append([0.0, 0.0, 0.0])
                counts.append(0)
            key_of[v] = s
            counts[s] += 1
            for a in range(3):
                sums[s][a] += pos[3 * v + a]
                nsum[s][a] += nor[3 * v + a]
        idx = array("I")
        seen = set()
        for t in range(0, len(m.indices), 3):
            a, b, c = key_of[m.indices[t]], key_of[m.indices[t + 1]], key_of[m.indices[t + 2]]
            if a == b or b == c or a == c:
                continue
            tri = (a, b, c)
            canon = min(tri, tri[1:] + tri[:1], tri[2:] + tri[:2])
            if canon in seen:                     # two clustered triangles that came to the same corners
                continue
            seen.add(canon)
            idx.extend(tri)
        positions, normals = array("f"), array("f")
        for s, n in zip(sums, counts):
            positions.extend((s[0] / n, s[1] / n, s[2] / n))
        for ns in nsum:
            ln = math.sqrt(ns[0] ** 2 + ns[1] ** 2 + ns[2] ** 2) or 1.0
            normals.extend((ns[0] / ln, ns[1] / ln, ns[2] / ln))
        if len(idx):
            mats.append(Material(m.colour, m.opacity, positions, normals, idx))
    return Mesh(mats)
