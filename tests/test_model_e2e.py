"""The 3D placement against KiCad itself: a real module is laid out and written, `kicad-cli pcb export glb` exports the written board, and
every part's model in the export is compared with the placement matrix the plan document carries applied to the mesh the converter cached.
Step B (the plan's transform against what the write step writes) is covered because the board compared against is the written one; a part
the plan flipped is in the set. Pads and models move together: a pad's position in the footprint's own frame, put through the same matrix,
lands on the plan's pad."""
import math

import pytest

from placemat import model_cache, model_convert as mc, model_mesh as mm, model_place
from placemat.board_geometry import members_of
from placemat.model_plan import ModelContext
from tests import real_modules
from tests.conftest import needs_kicad

CLI = mc.find_kicad_cli()
pytestmark = [needs_kicad, pytest.mark.skipif(CLI is None, reason="kicad-cli is not installed")]

MODULE = "usbconverter"                # its parts stand turned 0, 90, 180 and 270; one is put on the back below


def _one_part_on_the_back(text):
    text = text.replace('board.place(Part("r_vbus_en"), at=Beside(CTL, Edge.SOUTH, gap=VIA_ROWS, align=pin(4)),',
                        'board.place(Part("r_vbus_en"), at=Beside(CTL, Edge.SOUTH, gap=VIA_ROWS, align=pin(4)), face=Face.BACK,')
    return text.replace("from placemat import (board,", "from placemat import (Face, board,", 1)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e3d")
    result, drc, pcb = real_modules.run(tmp, MODULE, keep_going=True, edit=_one_part_on_the_back)
    plan = result.plan
    ctx = ModelContext(pcb)
    placed = []
    for step in plan.steps:
        if step.placement is None or step.item not in plan._items:
            continue
        for fp in members_of(plan._items[step.item]):
            if fp.ref in plan.occupancy.items:
                placed.append((fp, ctx.members(plan, fp)))
    cfg = mc.Config(cache_dir=str(tmp / "cache"), cache_mb=256)
    cache = model_cache.Cache(cfg.cache_dir, cfg.cache_mb)
    mc.run_batch(list(ctx.jobs_by_id.values()), cfg, CLI, cache, lambda e: None)
    glb = mc.Glb(mc.export_glb(CLI, __import__("pathlib").Path(pcb), 300))
    return plan, ctx, placed, cache, glb


def _axes(points):
    return [sorted(p[k] for p in points) for k in range(3)]


def _world_vertices(glb, ref):
    """Every vertex of `ref`'s node in the export, in mm, scene frame (x, up, board y)."""
    out = []
    for node, _, world, mesh_index in glb.walk():
        if node != ref:
            continue
        for prim in glb.json["meshes"][mesh_index]["primitives"]:
            pos = glb.accessor(prim["attributes"]["POSITION"])
            for v in range(len(pos) // 3):
                x, y, z = pos[3 * v], pos[3 * v + 1], pos[3 * v + 2]
                out.append(tuple(1000.0 * (world[r][0] * x + world[r][1] * y + world[r][2] * z + world[r][3]) for r in range(3)))
    return out


def test_every_model_in_kicads_export_is_where_the_plans_matrix_puts_the_cached_mesh(built):
    plan, ctx, placed, cache, glb = built
    checked, flipped, tested_back = 0, 0, 0
    for fp, models in placed:
        for m in models:
            if m["state"] not in ("ok", "vrml") or not m["id"] or not cache.has(m["id"]):
                continue
            mesh = mm.read_pmm(cache.get(m["id"]).read_bytes())
            mat = m["matrix"]
            ours = []
            for mat_ in mesh.materials:
                p = mat_.positions
                for v in range(len(p) // 3):
                    x, y, z = p[3 * v], p[3 * v + 1], p[3 * v + 2]
                    ours.append(tuple(mat[i] * x + mat[4 + i] * y + mat[8 + i] * z + mat[12 + i] for i in range(3)))
            theirs = _world_vertices(glb, fp.ref)
            if not theirs:
                continue
            assert len(ours) == len(theirs), fp.ref
            for a, b in zip(_axes(ours), _axes(theirs)):
                assert max(abs(p - q) for p, q in zip(a, b)) < 1e-3, "%s: a vertex differs by more than a micrometre" % fp.ref
            geom = plan.occupancy.items[fp.ref]
            flipped += geom.reference.face != fp.face
            tested_back += geom.reference.face.value == "back"
            checked += 1
    assert checked >= 5 and flipped >= 1, (checked, flipped)             # the set has a part the plan flipped


def test_a_pad_and_a_model_move_together_the_pads_footprint_frame_point_through_the_matrix_lands_on_the_plans_pad(built):
    plan, ctx, placed, cache, glb = built
    from types import SimpleNamespace
    n = 0
    for fp, models in placed:
        if not fp.pads or not models or not models[0]["id"]:
            continue
        occ = plan.occupancy
        geom = occ.items[fp.ref]
        from placemat.placement import Placement
        t = occ._transform(SimpleNamespace(reference=Placement(fp.location, fp.rotation, fp.face)), geom.reference)
        flipped = geom.reference.face != fp.face
        ident = ("m.step", (0, 0, 0), (0, 0, 0), (1, 1, 1), True, 1.0)
        mat = model_place.placement(ident, location=(fp.location.x, fp.location.y), rotation=fp.rotation, face=fp.face.value, to=t, flipped=flipped,
                                    thickness=ctx.thickness)
        pad = fp.pads[0]
        c = pad.box.center
        th = math.radians(fp.rotation)                                   # the pad in the footprint's own page frame (before its turn and location)
        dx, dy = c.x - fp.location.x, c.y - fp.location.y
        qx, qy = dx * math.cos(th) - dy * math.sin(th), dx * math.sin(th) + dy * math.cos(th)
        x, y = (qx, -qy) if fp.face.value == "front" else (qx, qy)       # the model frame's x, y of that library point
        got = (mat[0] * x + mat[4] * y + mat[12], mat[2] * x + mat[6] * y + mat[14])
        want = occ.pad_location(fp.ref, pad.number)
        assert got == pytest.approx((want.x, want.y), abs=1e-3), fp.ref
        n += 1
        if n >= 12:
            break
    assert n >= 5
