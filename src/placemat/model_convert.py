"""The model converter: STEP and VRML models to the meshes the studio's 3D view draws, into the shared cache (model_cache.py).

It runs as its own process (`python -m placemat.model_convert`; JSON lines on stdin and stdout, as the studio's resolve worker does) so the
studio and the page stay responsive while a batch runs, and a `kicad-cli` or pcbnew failure here cannot take a resolve down. It only ever
adds items to scratch boards (a footprint duplicated, a model entry added), never removes one.

A batch is one scratch board with a footprint per model, each at its own spot on the front at orientation 0 with an identity model entry,
exported by `kicad-cli pcb export glb --no-board-body --user-origin 0x0mm`. The GLB is read here (standard library only) and each model's
mesh is rewritten from KiCad's export frame (x = model x, y = height, z = -model y, metres, the model plane at 1.595 mm on a 1.6 mm board)
into the model frame (x right, y up the footprint's page, z up out of the board, millimetres, the plane subtracted), simplified to the
triangle cap and written to the cache. A model that is missing from the output fails alone and is tried by itself. A VRML model with no STEP
beside it is read by model_vrml.py and skips `kicad-cli`.

At start-up a self-test converts a known prism on a front and a back footprint: the model planes must be where model_place.py says (the
front at T - 0.005 and the back at -0.085) and the prism's box must come out in the model frame. A KiCad that moves them is refused, with its
version, rather than shifting every part in z.

Job: {"id", "kind": "file" | "embedded" | "vrml", "path"} for a file, plus {"board", "ref", "name"} for an embedded model (the footprint is
duplicated from the board file, which keeps its embedded files)."""
from __future__ import annotations

import gzip
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from array import array
from dataclasses import dataclass
from pathlib import Path

from . import model_cache, model_mesh as mm, model_place

THICKNESS = model_place.DEFAULT_THICKNESS
SELFTEST_MODEL = Path(__file__).with_name("data") / "prism_L.step"
SELFTEST_BOX = (0.0, 0.0, 0.0, 4.0, 2.0, 1.0)            # the prism's box in its own frame, mm


class ConvertError(Exception):
    """A conversion that did not work, with a sentence for the page."""


@dataclass
class Config:
    kicad_cli: str = ""
    batch: int = 8
    timeout_s: int = 120
    model_tris: int = 30000
    cache_dir: str = ""
    cache_mb: int = 512


def find_kicad_cli(setting: str = "") -> str | None:
    if setting:
        return setting if os.path.isfile(setting) else shutil.which(setting)
    return shutil.which("kicad-cli")


# ---------------------------------------------------------------- GLB
_COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class Glb:
    def __init__(self, data: bytes):
        if len(data) < 20 or data[:4] != b"glTF":
            raise ConvertError("kicad-cli wrote no GLB")
        self.json, self.bin, at = None, b"", 12
        while at + 8 <= len(data):
            ln, kind = struct.unpack_from("<II", data, at)
            chunk = data[at + 8:at + 8 + ln]
            if kind == 0x4E4F534A:
                self.json = json.loads(chunk.decode())
            elif kind == 0x004E4942:
                self.bin = chunk
            at += 8 + ln
        if self.json is None:
            raise ConvertError("the GLB has no description")

    def accessor(self, i: int):
        a = self.json["accessors"][i]
        view = self.json["bufferViews"][a["bufferView"]]
        code, size = _COMPONENT[a["componentType"]]
        width = _WIDTH[a["type"]]
        n = a["count"] * width
        start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = view.get("byteStride", 0)
        out = array(code)
        if stride and stride != size * width:
            for k in range(a["count"]):
                out.extend(struct.unpack_from("<%d%s" % (width, code), self.bin, start + k * stride))
        else:
            out.frombytes(self.bin[start:start + n * size])
            if sys.byteorder == "big":
                out.byteswap()
        return out

    def node_matrix(self, node: dict) -> list:
        """The 4x4 (row-major lists) of one node's own transform."""
        if "matrix" in node:
            m = node["matrix"]
            return [[m[c * 4 + r] for c in range(4)] for r in range(4)]
        tx, ty, tz = node.get("translation", (0, 0, 0))
        qx, qy, qz, qw = node.get("rotation", (0, 0, 0, 1))
        sx, sy, sz = node.get("scale", (1, 1, 1))
        r = [[1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
             [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
             [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)]]
        return [[r[0][0] * sx, r[0][1] * sy, r[0][2] * sz, tx], [r[1][0] * sx, r[1][1] * sy, r[1][2] * sz, ty],
                [r[2][0] * sx, r[2][1] * sy, r[2][2] * sz, tz], [0, 0, 0, 1]]

    def walk(self):
        """Every mesh node as (the node's name or its nearest named ancestor's, the mesh's name, world 4x4, mesh index)."""
        out = []
        nodes = self.json["nodes"]

        def mul(a, b):
            return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

        def go(i, parent, name):
            n = nodes[i]
            m = mul(parent, self.node_matrix(n))
            name = n.get("name", name) if "mesh" not in n else name
            if "mesh" in n:
                out.append((name, self.json["meshes"][n["mesh"]].get("name", ""), m, n["mesh"]))
            for c in n.get("children", ()):
                go(c, m, n.get("name", name))
        ident = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
        for s in self.json.get("scenes", [{"nodes": [0]}])[:1]:
            for i in s["nodes"]:
                go(i, ident, "")
        return out

    def materials(self) -> list:
        res = []
        for m in self.json.get("materials", ()):
            f = m.get("pbrMetallicRoughness", {}).get("baseColorFactor", (0.8, 0.8, 0.8, 1.0))
            res.append((tuple(_srgb(v) for v in f[:3]), round(float(f[3]), 3) if len(f) > 3 else 1.0))
        return res


def _srgb(v: float) -> int:
    v = max(0.0, min(1.0, float(v)))
    c = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return int(round(c * 255))


def mesh_of(glb: Glb, mesh_index: int, world: list, origin_mm: tuple, plane_mm: float) -> mm.Mesh:
    """One GLB mesh in the model frame: world metres to mm, x kept, y = -z, z = height less the plane, the node's `origin_mm` (board x, y)
    taken off. Triangles with a repeated corner are dropped."""
    mats = glb.materials()
    by_mat: dict = {}
    for prim in glb.json["meshes"][mesh_index]["primitives"]:
        if prim.get("mode", 4) != 4:
            continue
        pos = glb.accessor(prim["attributes"]["POSITION"])
        nor = glb.accessor(prim["attributes"]["NORMAL"]) if "NORMAL" in prim["attributes"] else None
        idx = glb.accessor(prim["indices"]) if "indices" in prim else array("I", range(len(pos) // 3))
        new_pos, new_nor = array("f"), array("f")
        for v in range(len(pos) // 3):
            x, y, z = pos[3 * v], pos[3 * v + 1], pos[3 * v + 2]
            wx = world[0][0] * x + world[0][1] * y + world[0][2] * z + world[0][3]
            wy = world[1][0] * x + world[1][1] * y + world[1][2] * z + world[1][3]
            wz = world[2][0] * x + world[2][1] * y + world[2][2] * z + world[2][3]
            new_pos.extend((wx * 1000.0 - origin_mm[0], -(wz * 1000.0 - origin_mm[1]), wy * 1000.0 - plane_mm))
            if nor is not None:
                nx, ny, nz = nor[3 * v], nor[3 * v + 1], nor[3 * v + 2]
                wnx = world[0][0] * nx + world[0][1] * ny + world[0][2] * nz
                wny = world[1][0] * nx + world[1][1] * ny + world[1][2] * nz
                wnz = world[2][0] * nx + world[2][1] * ny + world[2][2] * nz
                ln = math.sqrt(wnx * wnx + wny * wny + wnz * wnz) or 1.0
                new_nor.extend((wnx / ln, -wnz / ln, wny / ln))
            else:
                new_nor.extend((0.0, 0.0, 1.0))
        mi = prim.get("material", 0)
        colour, opacity = mats[mi] if mi < len(mats) else ((204, 204, 204), 1.0)
        acc = by_mat.setdefault((colour, opacity), mm.Material(colour, opacity, array("f"), array("f"), array("I")))
        base = len(acc.positions) // 3
        acc.positions.extend(new_pos)
        acc.normals.extend(new_nor)
        for t in range(0, len(idx), 3):
            a, b, c = idx[t], idx[t + 1], idx[t + 2]
            if a != b and b != c and a != c:
                acc.indices.extend((base + a, base + b, base + c))
    return mm.Mesh([m for m in by_mat.values() if len(m.indices)])


# ---------------------------------------------------------------- the scratch board and kicad-cli
def _pcbnew():
    from .kicad.quiet import import_pcbnew
    return import_pcbnew()


_boards: dict = {}


def _source_board(path: str):
    """A board file loaded once per process (embedded models are duplicated from it)."""
    key = (path, os.stat(path).st_mtime_ns)
    b = _boards.get(key)
    if b is None:
        from .kicad.quiet import quiet_stderr
        pcbnew = _pcbnew()
        with quiet_stderr():
            b = pcbnew.LoadBoard(path)
        _boards.clear()
        _boards[key] = b
    return b


def _spot(i: int) -> tuple:
    """Where job `i` stands on the scratch board, mm: a row of spots 40 mm apart, wrapping, so no two models overlap."""
    return 40.0 * (i % 8) + 20.0, 40.0 * (i // 8) + 20.0


def _scratch(jobs: list, folder: Path, back: set = frozenset()) -> Path:
    pcbnew = _pcbnew()
    board = pcbnew.BOARD()
    for i, job in enumerate(jobs):
        x, y = _spot(i)
        if job["kind"] == "embedded":
            fp = _source_board(job["board"])
            src = next((f for f in fp.GetFootprints() if f.GetReference() == job["ref"]), None)
            if src is None:
                raise ConvertError("the footprint %s is not on the board file" % job["ref"])
            item = src.Duplicate(False)
            item = pcbnew.Cast_to_FOOTPRINT(item) if not hasattr(item, "Models") else item
            if item.IsFlipped():
                item.Flip(item.GetPosition(), False)
            item.SetOrientationDegrees(0)
            models = item.Models()
            for k in range(len(models)):                         # by index: iterating the list hands out copies
                m = models[k]
                m.m_Offset = pcbnew.VECTOR3D(0, 0, 0)
                m.m_Rotation = pcbnew.VECTOR3D(0, 0, 0)
                m.m_Scale = pcbnew.VECTOR3D(1, 1, 1)
        else:
            item = pcbnew.FOOTPRINT(board)
            m = pcbnew.FP_3DMODEL()
            m.m_Filename = job["path"]
            item.Models().push_back(m)
        item.SetReference("M%d" % i)
        item.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        if i in back:
            item.Flip(item.GetPosition(), False)
        board.Add(item)
    path = folder / "scratch.kicad_pcb"
    from .kicad.quiet import quiet_stderr
    with quiet_stderr():
        board.Save(str(path))
    return path


def export_glb(cli: str, pcb: Path, timeout_s: int) -> bytes:
    out = pcb.with_suffix(".glb")
    try:
        r = subprocess.run([cli, "pcb", "export", "glb", "--force", "--no-board-body", "--user-origin", "0x0mm", "-o", str(out), str(pcb)],
                           capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise ConvertError("kicad-cli took longer than %d s" % timeout_s) from None
    except OSError as e:
        raise ConvertError("kicad-cli could not be run: %s" % e) from None
    if r.returncode != 0 or not out.is_file():
        raise ConvertError("kicad-cli failed (%d): %s" % (r.returncode, (r.stderr or r.stdout).strip().splitlines()[-1:] or ""))
    return out.read_bytes()


def kicad_version(cli: str) -> str:
    try:
        return subprocess.run([cli, "version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def convert_step_batch(jobs: list, cfg: Config, cli: str, back: set = frozenset()) -> dict:
    """{job index: Mesh} for the jobs `kicad-cli` could export in one go (a job missing from the output is left out)."""
    with tempfile.TemporaryDirectory(prefix="placemat-3d-") as d:
        pcb = _scratch(jobs, Path(d), back)
        glb = Glb(export_glb(cli, pcb, cfg.timeout_s))
        plane_front, plane_back = model_place.planes(THICKNESS)
        meshes: dict = {}
        want = {"M%d" % i: i for i in range(len(jobs))}
        walked = glb.walk()
        per_node: dict = {}
        for node, *_ in walked:
            per_node[node] = per_node.get(node, 0) + 1
        for node, mesh_name, world, mesh_index in walked:
            i = want.get(node)
            if i is None:
                continue
            job = jobs[i]
            stem = Path(job.get("name") or job.get("path") or "").stem
            if stem and mesh_name and mesh_name != stem and per_node[node] > 1:
                continue                                         # a footprint with several models: this mesh is another's
            x, y = _spot(i)
            part = mesh_of(glb, mesh_index, world, (x, y), plane_back if i in back else plane_front)
            if i in meshes:
                meshes[i].materials.extend(part.materials)
            else:
                meshes[i] = part
        return meshes


def read_vrml_file(path: str) -> mm.Mesh:
    from .model_vrml import VrmlError, read_vrml
    try:
        raw = Path(path).read_bytes()
        if path.lower().endswith(".wrz") or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return read_vrml(raw.decode("utf-8", errors="replace"))
    except (OSError, VrmlError) as e:
        raise ConvertError(str(e)) from None


def finish(mesh: mm.Mesh, cfg: Config) -> bytes:
    small, _ = mm.decimate(mesh, cfg.model_tris)
    return mm.write_pmm(small)


# ---------------------------------------------------------------- the self-test
def self_test(cfg: Config, cli: str) -> dict:
    """Convert the prism on a front and a back footprint: {"ok": bool, "message", "front": plane, "back": plane, "version"}. Refuses when
    the planes are not where model_place says, or the prism's box does not come out in the model frame."""
    version = kicad_version(cli)
    jobs = [{"kind": "file", "path": str(SELFTEST_MODEL), "name": SELFTEST_MODEL.name}] * 2
    try:
        glb = Glb(export_glb(cli, _scratch_files(jobs, back={1}), cfg.timeout_s))
    except ConvertError as e:
        return {"ok": False, "message": str(e), "version": version}
    plane_front, plane_back = model_place.planes(THICKNESS)
    rows = {n: (m, w) for n, _, w, m in glb.walk()}
    found = {}
    for n, (mesh_index, world) in rows.items():
        i = int(n[1:])
        x, y = _spot(i)
        mesh = mesh_of(glb, mesh_index, world, (x, y), plane_back if i == 1 else plane_front)
        found[i] = mm.bbox(mesh)
    if set(found) != {0, 1}:
        return {"ok": False, "message": "kicad-cli exported no prism (KiCad %s)" % version, "version": version}
    f = found[0]
    ok_front = all(abs(a - b) < 2e-3 for a, b in zip(f, SELFTEST_BOX))
    g = found[1]
    ok_back = abs(g[2] - -1.0) < 2e-3 and abs(g[5]) < 2e-3                       # hangs 1 mm below its own face
    if not (ok_front and ok_back):
        return {"ok": False, "version": version, "front": f, "back": g,
                "message": "KiCad %s puts its model planes somewhere else than this converter expects (front box %s, back box %s)" % (version, f, g)}
    return {"ok": True, "message": "", "version": version, "front": f, "back": g}


def _scratch_files(jobs: list, back: set) -> Path:
    d = Path(tempfile.mkdtemp(prefix="placemat-3d-"))
    return _scratch([dict(j, kind="file") for j in jobs], d, back)


# ---------------------------------------------------------------- a batch
def run_batch(jobs: list, cfg: Config, cli: str | None, cache: model_cache.Cache, emit) -> None:
    """Convert `jobs` (those not already in the cache) and emit `model` events {id, state, tris, message}. A job missing from the batch's
    output is tried alone; one that still fails is recorded as a failure."""
    todo = [j for j in jobs if not cache.has(j["id"]) and cache.failure(j["id"]) is None]
    for j in jobs:
        if cache.has(j["id"]):
            emit({"ev": "model", "id": j["id"], "state": "ok", "tris": None, "message": ""})
        elif cache.failure(j["id"]) is not None:
            emit({"ev": "model", "id": j["id"], "state": "failed", "tris": None, "message": cache.failure(j["id"])})
    done, total = 0, len(todo)

    def ok(job, mesh):
        data = finish(mesh, cfg)
        cache.put(job["id"], data)
        emit({"ev": "model", "id": job["id"], "state": "ok", "tris": mm.read_pmm(data).header["tris"], "message": ""})

    def fail(job, message):
        cache.put_failure(job["id"], message)
        emit({"ev": "model", "id": job["id"], "state": "failed", "tris": None, "message": message})

    step = []
    for j in todo:
        if j["kind"] == "vrml":
            try:
                ok(j, read_vrml_file(j["path"]))
            except ConvertError as e:
                fail(j, str(e))
            done += 1
            emit({"ev": "progress", "done": done, "total": total, "current": j["id"]})
        else:
            step.append(j)
    for a in range(0, len(step), max(1, cfg.batch)):
        batch = step[a:a + max(1, cfg.batch)]
        if cli is None:
            for j in batch:
                fail(j, "3D needs kicad-cli on the path, or set studio_3d_kicad_cli")
            done += len(batch)
            continue
        got, why = {}, ""
        try:
            got = convert_step_batch(batch, cfg, cli)
        except ConvertError as e:
            why = str(e)
        except Exception as e:                                   # pcbnew or the scratch board went wrong: this batch fails, not the process
            why = "%s: %s" % (type(e).__name__, e)
        for i, j in enumerate(batch):
            if i in got and len(got[i].materials):
                ok(j, got[i])
            elif len(batch) > 1:                                  # a bad model must not fail its batch: tried alone
                try:
                    one = convert_step_batch([j], cfg, cli)
                    if 0 in one and len(one[0].materials):
                        ok(j, one[0])
                    else:
                        fail(j, "kicad-cli exported no mesh for this model")
                except ConvertError as e:
                    fail(j, str(e))
                except Exception as e:
                    fail(j, "%s: %s" % (type(e).__name__, e))
            else:
                fail(j, why or "kicad-cli exported no mesh for this model")
            done += 1
            emit({"ev": "progress", "done": done, "total": total, "current": j["id"]})
    cache.trim(in_use={j["id"] for j in jobs})


# ---------------------------------------------------------------- the process
def main() -> int:
    cfg = Config()
    cache = None
    cli = None

    def emit(ev: dict) -> None:
        sys.stdout.write(json.dumps(ev, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        cmd = msg.get("cmd")
        if cmd == "start":
            cfg = Config(**{k: v for k, v in msg.get("cfg", {}).items() if k in Config.__dataclass_fields__})
            cache = model_cache.Cache(model_cache.default_dir(cfg.cache_dir), cfg.cache_mb)
            cache.sweep_versions()
            cache.trim()
            cli = find_kicad_cli(cfg.kicad_cli)
            test = {"ok": False, "message": "3D needs kicad-cli on the path, or set studio_3d_kicad_cli"} if cli is None else self_test(cfg, cli)
            emit({"ev": "ready", "cli": cli or "", "selftest": test, "cache": str(cache.dir)})
        elif cmd == "batch" and cache is not None:
            try:
                run_batch(msg.get("jobs", []), cfg, cli, cache, emit)
            except Exception as e:                                # the process outlives any one batch
                emit({"ev": "error", "message": "%s: %s" % (type(e).__name__, e)})
            emit({"ev": "batch_done", "n": len(msg.get("jobs", []))})
        elif cmd == "retry" and cache is not None:
            cache.retry(msg.get("id"))
        elif cmd == "quit":
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
