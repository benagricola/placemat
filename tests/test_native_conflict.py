"""native.conflict (the boolean core of Occupancy._conflict / _drawn_conflict,
in native/src/shapes.rs) agrees with the live Python method on real shape
kinds, across randomised pairs and offsets.

This gates wiring native into Occupancy.legal() (plan Task 3, step 3): the
plan calls for zero mismatches over a large randomised run before that
wiring happens, because a mismatch here would mean legal() could pick a
different candidate, or blame the wrong obstacle, with native on.
"""
import math
import random

import pytest

placemat_native = pytest.importorskip("placemat_native")

from placemat.values import Box, CopperLayer, Face, Location
from placemat.occupancy import Occupancy, Shape
from tests.fixtures import board_geometry, footprint, pad, track
from tests.test_occupancy import occ_with


_LAYER_ORDER = list(CopperLayer)


def _encode_faces(faces) -> int:
    bits = 0
    if Face.FRONT in faces:
        bits |= 1
    if Face.BACK in faces:
        bits |= 2
    return bits


def _encode_layers(layers) -> int:
    bits = 0
    for l in layers:
        bits |= 1 << _LAYER_ORDER.index(l)
    return bits


def _py_shape(s: Shape, owner_is_footprint: bool):
    return (s.kind, _encode_faces(s.faces), _encode_layers(s.layers), s.net or "", tuple(s.poly), owner_is_footprint)


def _all_shapes(occ: Occupancy):
    """Every Shape the occupancy currently holds, paired with whether its
    owner is a footprint (== occ._footprint_refs, confirmed equal to "in
    occ.items" since every footprint is pre-registered in __init__ and no
    other owner is ever added to occ.items). Adds a synthetic npth shape
    (none of the fixture footprints draw one) so the courtyard-over-npth,
    npth-cuts-copper and body/npth rules get covered too."""
    out = []
    for owner, g in occ.items.items():
        for s in g.shapes:
            out.append((s, owner in occ._footprint_refs))
    for c in occ.copper:
        out.append((c, c.owner in occ._footprint_refs))
    hole_poly = tuple((10.0 + 0.4 * math.cos(2 * math.pi * i / 12), 10.0 + 0.4 * math.sin(2 * math.pi * i / 12))
                      for i in range(12))
    hole = Shape("U1", "npth", frozenset([Face.FRONT, Face.BACK]), frozenset(CopperLayer), "", hole_poly, Box.of_points(hole_poly))
    out.append((hole, True))
    return out


def _cfg_kwargs(occ: Occupancy):
    net_clearance = {n: occ.geometry.netclass(n).clearance for n in occ.geometry.nets}
    return dict(touch=occ._touch, vias_block_courtyards=occ.vias_block_courtyards,
                silk_clearance=occ.silk_clearance, component_spacing=occ.component_spacing,
                default_clearance=occ.geometry.default_clearance, net_clearance=net_clearance)


def _rich_occupancy(envelope="union", vias_block_courtyards=False):
    fps = [
        footprint("U1", 10, 10, w=4, h=2, fab=(9, 9, 11, 11), silk_boxes=[(8.5, 8.5, 11.5, 9.0)], mask_grow=0.1),
        footprint("U2", 20, 10, w=3, h=3, through=True, fab=(18.5, 8.5, 21.5, 11.5)),
        footprint("U3", 10, 20, w=2, h=2, silk_boxes=[(9, 19, 11, 19.2)]),
    ]
    g = board_geometry(fps, width=60, height=60, silk_clearance=0.1)
    from placemat.settings import Settings
    import dataclasses
    settings = dataclasses.replace(Settings(), place_envelope=envelope)
    occ = Occupancy(g, edge_margin=1.0, settings=settings, vias_block_courtyards=vias_block_courtyards,
                    component_spacing=0.2)
    via_poly = ((14.0, 14.0), (14.3, 14.0), (14.3, 14.3), (14.0, 14.3))
    occ.add_copper([Shape("", "through", frozenset([Face.FRONT, Face.BACK]), frozenset(CopperLayer),
                          "GND", via_poly, Box.of_points(via_poly))])
    return occ


def _offset(poly, dx, dy):
    return tuple((x + dx, y + dy) for x, y in poly)


def _shifted(s: Shape, dx: float, dy: float) -> Shape:
    poly = _offset(s.poly, dx, dy)
    return Shape(s.owner, s.kind, s.faces, s.layers, s.net, poly, Box.of_points(poly), s.label)


@pytest.mark.parametrize("envelope", ["courtyard", "physical", "union"])
def test_conflict_agrees_with_python_on_randomised_shape_pairs(envelope):
    occ = _rich_occupancy(envelope=envelope)
    shapes = _all_shapes(occ)
    assert len(shapes) >= 8, "fixture should produce a variety of shape kinds"
    cfg = _cfg_kwargs(occ)
    rnd = random.Random(20260924)
    mismatches = []
    n = 0
    for _ in range(20000):
        (s, s_is_fp), (o, o_is_fp) = rnd.choice(shapes), rnd.choice(shapes)
        dx, dy = rnd.uniform(-3, 3), rnd.uniform(-3, 3)
        s_moved = _shifted(s, dx, dy) if rnd.random() < 0.5 else s
        o_moved = _shifted(o, dx * rnd.uniform(-1, 1), dy * rnd.uniform(-1, 1)) if rnd.random() < 0.5 else o
        clearance = rnd.choice([None, None, None, 0.1, 0.3])
        py = occ._conflict(s_moved, o_moved, clearance) is not None
        native = placemat_native.conflict(_py_shape(s_moved, s_is_fp), _py_shape(o_moved, o_is_fp), clearance, **cfg)
        n += 1
        if py != native:
            mismatches.append((s_moved.kind, o_moved.kind, dx, dy, clearance, py, native))
    assert not mismatches, "%d/%d mismatches: %s" % (len(mismatches), n, mismatches[:5])


def test_conflict_agrees_with_vias_blocking_courtyards():
    occ = _rich_occupancy(envelope="courtyard", vias_block_courtyards=True)
    shapes = _all_shapes(occ)
    cfg = _cfg_kwargs(occ)
    rnd = random.Random(7)
    mismatches = []
    for _ in range(6000):
        (s, s_is_fp), (o, o_is_fp) = rnd.choice(shapes), rnd.choice(shapes)
        dx, dy = rnd.uniform(-1, 1), rnd.uniform(-1, 1)
        o_moved = _shifted(o, dx, dy)
        py = occ._conflict(s, o_moved, None) is not None
        native = placemat_native.conflict(_py_shape(s, s_is_fp), _py_shape(o_moved, o_is_fp), None, **cfg)
        if py != native:
            mismatches.append((s.kind, o_moved.kind, dx, dy))
    assert not mismatches


def test_conflict_agrees_at_the_courtyard_touch_boundary():
    """The c785a04 epsilon: two courtyards overlapping by exactly
    place.courtyard_touch must not conflict, even when the depth reads as
    0.0200000000000013 from rounding."""
    occ = occ_with(footprint("R1", 11.9, 10), width=60)
    cfg = _cfg_kwargs(occ)
    r1 = occ.items["R1"].shapes[0]
    assert r1.kind == "courtyard"
    r2_poly = tuple(((16.08 - 2.1, 10 - 1.0), (16.08 + 2.1, 10 - 1.0), (16.08 + 2.1, 10 + 1.0), (16.08 - 2.1, 10 + 1.0)))
    r2 = Shape("R2", "courtyard", r1.faces, frozenset(), "", r2_poly, Box.of_points(r2_poly))
    assert occ._conflict(r1, r2, None) is None
    assert placemat_native.conflict(_py_shape(r1, True), _py_shape(r2, True), None, **cfg) is False
