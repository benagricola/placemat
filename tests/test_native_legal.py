"""End-to-end: a native-assisted re-implementation of the near-obstacle
search inside Occupancy.legal() (obstacles registered once via
NativeObstacles, queried once per candidate) agrees with the live,
unmodified Occupancy.legal() - verdict, reason string and blame - on
randomised candidates against both a synthetic board and a real fixture
board.

This is the gate plan Task 3 step 3 sets before wiring native into
Occupancy.legal() itself: zero mismatches here first. The helper below
(`_native_legal`) is deliberately NOT src/placemat code yet - it exists
only to prove the integration point out before it is wired in.
"""
import math
import pathlib
import random

import pytest

placemat_native = pytest.importorskip("placemat_native")

from placemat.occupancy import Occupancy, ShapeIndex
from placemat.placement import Placement
from placemat.values import CopperLayer, Face, Location
from tests.fixtures import board_geometry, footprint
from tests.test_native_conflict import _cfg_kwargs, _encode_faces, _encode_layers


def _py_shape_tuple(occ, s):
    return (s.kind, _encode_faces(s.faces), _encode_layers(s.layers), s.net or "", tuple(s.poly), s.owner,
            s.owner in occ._footprint_refs, (s.owner, s.label) in occ._leads)


def _native_legal(occ: Occupancy, item, placement: Placement, clearance=None):
    """What Occupancy.legal() would return with the near-obstacle search
    delegated to native: same edge/reservation checks (untouched Python,
    run first, exactly as legal() does), then one native call in place of
    `near()` + the per-shape loop, then the real _conflict re-run on the
    identified pair only. Returns (reason_or_None, blame_list) as
    occ.legal(..., blame=[]) does."""
    from placemat.occupancy import Blocker
    geom = occ._geometry(item)
    body = occ.shifted_body_box(item, placement)
    if occ.edge_margin is not None:
        if occ.board_shape is not None:
            why = occ.board_shape.why_not(body, occ.edge_margin)
            if why:
                return "body box %s is %s" % (_fmt(body), why), [Blocker("edge", "", frozenset())]
        elif occ.board_box is not None:
            inner = occ.board_box.inflate(-occ.edge_margin)
            if not inner.contains(body):
                return "edge", [Blocker("edge", "", frozenset())]
            if occ.board_cutouts:
                why = occ.board_cutouts.why_not(body, occ.edge_margin)
                if why:
                    return "cutout", [Blocker("edge", "", frozenset())]
    faces = {placement.face} | ({Face.FRONT, Face.BACK} if any(s.kind in ("through", "npth") for s in geom.shapes) else set())
    for r in occ.reservations:
        if r.layer is not None and r.layer.face not in faces:
            continue
        if (geom.owners & r.owners) or (geom.nets & r.allow):
            continue
        if r.overlaps(body):
            return "reservation", [Blocker("reservation", r.why, frozenset())]
    others = occ.obstacles(geom)
    cfg = _cfg_kwargs(occ)
    index = placemat_native.NativeObstacles(
        [_py_shape_tuple(occ, o) for o in others], cfg["touch"], cfg["vias_block_courtyards"],
        cfg["silk_clearance"], cfg["component_spacing"], cfg["default_clearance"], cfg["net_clearance"],
        occ._gap, occ._drawn_gap,
    )
    dx, dy = placement.location.x, placement.location.y
    candidates = []
    for s in occ._origin_shapes(item, geom, placement):
        sb = s.box.moved(dx, dy)
        poly = tuple((x + dx, y + dy) for x, y in s.poly)
        from placemat.occupancy import Shape
        candidates.append(Shape(s.owner, s.kind, s.faces, s.layers, s.net, poly, sb, s.label))
    hit = index.first_conflict([_py_shape_tuple(occ, c) for c in candidates], clearance)
    if hit is None:
        return None, []
    si, oi = hit
    why = occ._conflict(candidates[si], others[oi], clearance)
    if why is None:
        # native found a pair Python's own _conflict disagrees is a
        # conflict: a mismatch the test below must catch, not paper over.
        return "NATIVE_FALSE_POSITIVE:%s vs %s" % (candidates[si].kind, others[oi].kind), []
    return why, [Blocker(others[oi].kind, occ.who(others[oi].owner), frozenset(others[oi].faces))]


def _fmt(b):
    return "%.2f,%.2f..%.2f,%.2f" % (b.left, b.top, b.right, b.bottom)


def _is_edge_or_reservation(blame):
    return blame and blame[0].kind in ("edge", "reservation")


def _compare(occ, item, placement, clearance, mismatches):
    blame_py = []
    why_py = occ.legal(item, placement, clearance, blame=blame_py)
    if _is_edge_or_reservation(blame_py):
        return  # not native's concern; the helper above only reproduces this path, doesn't accelerate it
    why_native, blame_native = _native_legal(occ, item, placement, clearance)
    py_blame_tuple = [(b.kind, b.owner, b.faces) for b in blame_py]
    native_blame_tuple = [(b.kind, b.owner, b.faces) for b in blame_native]
    if (why_py is None) != (why_native is None) or why_py != why_native or py_blame_tuple != native_blame_tuple:
        mismatches.append((placement, why_py, why_native, py_blame_tuple, native_blame_tuple))


def _legal_both_ways(occ, item, placement, clearance):
    """Occupancy.legal() itself (the real, shipped code path), called once
    with native available and once with it monkeypatched off - not a
    reimplementation, the actual production method both times."""
    import placemat.geometry as geometry
    real_native = geometry._native
    blame_native = []
    why_native = occ.legal(item, placement, clearance, blame=blame_native)
    geometry._native = None
    try:
        blame_py = []
        why_py = occ.legal(item, placement, clearance, blame=blame_py)
    finally:
        geometry._native = real_native
    return (why_native, blame_native), (why_py, blame_py)


@pytest.mark.parametrize("board_name,envelope", [
    ("fairing/modules/SlotControl/layout/layout.kicad_pcb", "physical"),
    ("fairing/modules/SlotControl/layout/layout.kicad_pcb", "courtyard"),
    ("mnb/modules/MCU_RP2350B/layout/layout.kicad_pcb", "union"),
])
def test_the_actual_wired_legal_agrees_with_itself_native_on_and_off(board_name, envelope):
    """Occupancy.legal() is the method scan() actually calls; this toggles
    the real _native module reference it reads (not a hand-rolled stand-in)
    and compares its own two answers directly - the strongest test in this
    file, since it exercises exactly what ships."""
    pytest.importorskip("pcbnew")
    from placemat.kicad.read import read_board
    board = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / board_name
    if not board.exists():
        pytest.skip("fixture board not found")
    from placemat.settings import Settings
    import dataclasses
    g = read_board(board)
    settings = dataclasses.replace(Settings(), place_envelope=envelope)
    occ = Occupancy(g, edge_margin=0.2, settings=settings, component_spacing=0.2)
    rnd = random.Random(hash(("wired", board_name, envelope)) & 0xFFFFFFFF)
    fps = list(g.footprints)
    mismatches = []
    for _ in range(500):
        item = rnd.choice(fps)
        cx, cy = item.location.x, item.location.y
        x, y = cx + rnd.uniform(-8, 8), cy + rnd.uniform(-8, 8)
        rot = rnd.choice([0, 90, 180, 270])
        placement = Placement(Location(x, y), rot, item.face)
        clearance = rnd.choice([None, None, None, 0.1, 0.3])
        (why_n, blame_n), (why_p, blame_p) = _legal_both_ways(occ, item, placement, clearance)
        nb = [(b.kind, b.owner, b.faces) for b in blame_n]
        pb = [(b.kind, b.owner, b.faces) for b in blame_p]
        if why_n != why_p or nb != pb:
            mismatches.append((placement, why_n, why_p, nb, pb))
    assert not mismatches, mismatches[:5]


@pytest.mark.parametrize("envelope", ["courtyard", "physical", "union"])
def test_native_assisted_legal_agrees_with_python_on_a_synthetic_board(envelope):
    from tests.test_native_conflict import _rich_occupancy
    occ = _rich_occupancy(envelope=envelope)
    item = footprint("PROBE", 15, 15, w=3, h=2)
    rnd = random.Random(20260924)
    mismatches = []
    for _ in range(400):
        x, y = rnd.uniform(2, 58), rnd.uniform(2, 58)
        rot = rnd.choice([0, 90, 180, 270])
        clearance = rnd.choice([None, None, 0.1, 0.3])
        placement = Placement(Location(x, y), rot, Face.FRONT)
        _compare(occ, item, placement, clearance, mismatches)
    assert not mismatches, mismatches[:5]


@pytest.mark.parametrize("board_name,envelope", [
    ("fairing/modules/SlotControl/layout/layout.kicad_pcb", "physical"),
    ("fairing/modules/SlotControl/layout/layout.kicad_pcb", "courtyard"),
    ("fairing/modules/SlotControl/layout/layout.kicad_pcb", "union"),
    ("fairing/modules/Mcu/layout/layout.kicad_pcb", "physical"),
    ("mnb/modules/MCU_RP2350B/layout/layout.kicad_pcb", "union"),
])
def test_native_assisted_legal_agrees_with_python_on_real_fixture_boards(board_name, envelope):
    pytest.importorskip("pcbnew")
    from placemat.kicad.read import read_board
    board = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / board_name
    if not board.exists():
        pytest.skip("fixture board not found")
    from placemat.settings import Settings
    import dataclasses
    g = read_board(board)
    settings = dataclasses.replace(Settings(), place_envelope=envelope)
    occ = Occupancy(g, edge_margin=0.2, settings=settings, component_spacing=0.2)
    rnd = random.Random(hash((board_name, envelope)) & 0xFFFFFFFF)
    fps = list(g.footprints)
    mismatches = []
    for _ in range(800):
        item = rnd.choice(fps)
        cx, cy = item.location.x, item.location.y
        x, y = cx + rnd.uniform(-8, 8), cy + rnd.uniform(-8, 8)
        rot = rnd.choice([0, 90, 180, 270])
        placement = Placement(Location(x, y), rot, item.face)
        clearance = rnd.choice([None, None, None, 0.1, 0.3])
        _compare(occ, item, placement, clearance, mismatches)
    assert not mismatches, mismatches[:5]
