"""The current-path check judges each piece of copper by its own layer's
weight, read from the board's stackup: the inner-layer IPC-2221 constant
(k = 0.024) on an inner layer, against 0.048 on an outer one, and the
layer's own copper weight rather than a single [check] copper_oz."""
import dataclasses

import pytest

from placemat.board_geometry import CopperItem
from placemat.checks import current_paths, ipc2221_width_mm
from placemat.geometry import circle_polygon
from placemat.values import Box, CopperLayer, Location
from tests.fixtures import board_geometry, footprint, track


def _via(net, x, y, layers, size=0.3):
    """A via bridging the pads' face to the track's inner layer, so the
    net graph joins pad -> via -> track: a real board reaches an inner
    layer this way too, never by a pad claiming a layer it is not on."""
    ring = circle_polygon(Location(x, y), size / 2)
    return CopperItem("via", net, frozenset(layers), (ring,), Box.of_points(ring), None, size, 0.1, ((x, y),))


def test_the_inner_constant_needs_a_wider_track_than_the_outer_one():
    """Same current, same rise, same weight: the inner-layer formula
    needs more copper than the outer one (a smaller k means a bigger
    area for the same current)."""
    outer = ipc2221_width_mm(3.0, rise_c=10.0, copper_oz=1.0, k=0.048)
    inner = ipc2221_width_mm(3.0, rise_c=10.0, copper_oz=1.0, k=0.024)
    assert inner > outer


def test_a_track_on_an_inner_layer_is_judged_by_its_own_stackup_weight():
    """A 0.5 oz inner track (0.0175 mm, from the stackup) is judged with
    k = 0.024 and 0.5 oz - not the 1 oz outer default - so it needs a
    wider track than the same current would on F.Cu."""
    u = footprint("U1", 10, 10, nets=("VIN", "X"), fields={"Pm.I": "vin:3A"})
    c = footprint("C1", 30, 10, nets=("VIN", "GND"), fields={"Pm.I": "vin:3A"})
    wide = track("VIN", 8.6, 10, 28.6, 10, w=2.0, layer=CopperLayer.IN1)
    v1 = _via("VIN", 8.6, 10, (CopperLayer.F, CopperLayer.IN1))
    v2 = _via("VIN", 28.6, 10, (CopperLayer.F, CopperLayer.IN1))
    g = dataclasses.replace(board_geometry([u, c], copper=[v1, wide, v2]),
                             layers=(CopperLayer.F, CopperLayer.IN1, CopperLayer.B),
                             copper_mm={CopperLayer.IN1: 0.0175})
    v = {x.subject: x for x in current_paths(g)}["VIN"]
    need_inner = ipc2221_width_mm(3.0, 10.0, 0.0175 / 0.0350012, 0.024)
    assert v.limit == pytest.approx(need_inner, rel=1e-6)


def test_a_layer_missing_from_the_stackup_falls_back_to_1_oz():
    """A board with no explicit stackup (copper_mm empty for that layer)
    still judges an inner track with the inner constant, at the 1 oz
    fallback."""
    u = footprint("U1", 10, 10, nets=("VIN", "X"), fields={"Pm.I": "vin:3A"})
    c = footprint("C1", 30, 10, nets=("VIN", "GND"), fields={"Pm.I": "vin:3A"})
    wide = track("VIN", 8.6, 10, 28.6, 10, w=2.0, layer=CopperLayer.IN1)
    v1 = _via("VIN", 8.6, 10, (CopperLayer.F, CopperLayer.IN1))
    v2 = _via("VIN", 28.6, 10, (CopperLayer.F, CopperLayer.IN1))
    g = dataclasses.replace(board_geometry([u, c], copper=[v1, wide, v2]),
                             layers=(CopperLayer.F, CopperLayer.IN1, CopperLayer.B))
    v = {x.subject: x for x in current_paths(g)}["VIN"]
    assert v.limit == pytest.approx(ipc2221_width_mm(3.0, 10.0, 1.0, 0.024), rel=1e-6)
