"""Adopted routes on a real board, with no router: a track added to a copy
stands in for the router's, is adopted, and the next resolve writes it."""
import pytest

pytest.importorskip("pcbnew")

import dataclasses
import shutil

from placemat import routes
from placemat.kicad.drc import run_drc
from placemat.kicad.read import read_board
from placemat.kicad.write import apply_plan
from placemat.layout import Board
from placemat.values import CopperLayer, Net, Part, PadRef
from tests.conftest import needs_breakout, needs_kicad

pytestmark = [needs_kicad, needs_breakout]

NET = "TERM_NEAR_MID"


def _copy(breakout_pcb, dest):
    dest.mkdir()
    for ext in (".kicad_pcb", ".kicad_pro"):
        src = breakout_pcb.with_suffix(ext)
        if src.exists():
            shutil.copy(src, dest / ("layout" + ext))
    return dest / "layout.kicad_pcb"


def _board(geometry):
    b = Board(geometry, edge_margin=0.0)
    b.size(width=geometry.outline_box.width, height=geometry.outline_box.height, chamfer=2.0)
    return b


def _adopted(breakout_pcb, tmp_path):
    placed = _copy(breakout_pcb, tmp_path / "placed")
    routed = _copy(breakout_pcb, tmp_path / "routed")
    b = _board(read_board(routed))                  # the router's stand-in: one track on the net
    b.track(Net(NET), [PadRef(Part("term_near_ra"), NET), PadRef(Part("term_near_rb"), NET)],
            layer=CopperLayer.F, width=0.3)
    apply_plan(routed, b.resolve())
    return placed, routes.entries_from(read_board(placed), read_board(routed), [NET])


def _tracks(geometry):
    return sorted((tuple(sorted((round(a[0], 3), round(a[1], 3)) for a in c.anchors)), round(c.width_mm, 3))
                  for c in geometry.copper if c.kind == "track" and c.net == NET)


def test_an_adopted_track_is_written_on_the_next_run(breakout_pcb, tmp_path):
    placed, entries = _adopted(breakout_pcb, tmp_path)
    assert [e.net for e in entries] == [NET] and len(entries[0].tracks) == 1
    before = read_board(placed)
    drc_before = run_drc(placed, tmp_path / "drc0.json")
    plan = _board(before).resolve(routes=entries)
    assert plan.adopted == {NET: "held"}
    apply_plan(placed, plan)
    after = read_board(placed)
    added = list(_tracks(after))
    for t in _tracks(before):
        added.remove(t)
    assert [w for _, w in added] == [0.3]           # the adopted track, beside the board's own
    assert run_drc(placed, tmp_path / "drc1.json").real == drc_before.real


def test_an_adopted_track_whose_part_moved_is_dropped(breakout_pcb, tmp_path):
    placed, entries = _adopted(breakout_pcb, tmp_path)
    e = entries[0]
    ref = sorted(e.parts)[-1]
    kept = e.parts[ref]
    pads = {n: [x + 1.0, y] for n, (x, y) in kept["pads"].items()}             # as if it stood 1 mm away then
    moved = dataclasses.replace(e, parts={**e.parts, ref: {**kept, "pads": pads}})
    plan = _board(read_board(placed)).resolve(routes=[moved])
    assert ref in plan.adopted[NET]
    assert not [c for c in plan.copper if getattr(c, "net", None) == NET]
    assert any("adopted route %s dropped" % NET in f and ref in f for f in plan.findings)


def test_an_adopted_route_between_back_face_parts_is_drawn_where_it_was_routed(breakout_pcb, tmp_path):
    """A flipped part's orientation as KiCad reads it is not the placement's:
    the kept copper must come back where the router laid it."""
    import pcbnew
    from placemat.values import Face, Location
    gen = _copy(breakout_pcb, tmp_path / "gen")
    g0 = read_board(gen)
    fps = {fp.inst: fp for fp in g0.footprints}
    ra, rb = fps["term_near_ra"], fps["term_near_rb"]

    def board(g):
        b = _board(g)
        for fp in (ra, rb):
            b.place(Part(fp.inst), at=Location(fp.location.x, fp.location.y), rotation=90, face=Face.BACK)
        return b
    placed = _copy(breakout_pcb, tmp_path / "placed")
    apply_plan(placed, board(g0).resolve())
    gp = read_board(placed)
    by_ref = {fp.ref: fp for fp in gp.footprints}
    pa = [p for p in by_ref[ra.ref].pads if p.net == NET][0]
    pb = [p for p in by_ref[rb.ref].pads if p.net == NET][0]
    A, B = (pa.box.center.x + 0.05, pa.box.center.y), (pb.box.center.x, pb.box.center.y)
    M = (A[0] + 1.0, A[1] + 0.7)
    routed = tmp_path / "routed.kicad_pcb"
    shutil.copy(placed, routed)
    brd = pcbnew.LoadBoard(str(routed))
    for p, q in ((A, M), (M, B)):
        t = pcbnew.PCB_TRACK(brd)
        t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(p[0]), pcbnew.FromMM(p[1])))
        t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(q[0]), pcbnew.FromMM(q[1])))
        t.SetWidth(pcbnew.FromMM(0.2))
        t.SetLayer(pcbnew.B_Cu)
        t.SetNet(brd.FindNet(NET))
        brd.Add(t)
    brd.Save(str(routed))
    (e,) = routes.entries_from(gp, read_board(routed), [NET])
    plan = board(read_board(gen)).resolve(routes=[e])
    assert plan.adopted == {NET: "held"}
    got = sorted((round(p.x, 4), round(p.y, 4)) for c in plan.copper if getattr(c, "net", None) == NET
                 and hasattr(c, "start") for p in (c.start, c.end))
    assert got == sorted((round(x, 4), round(y, 4)) for x, y in (A, M, M, B))
