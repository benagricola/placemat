"""check current-path adds copper on parallel layers: where the load's route
crosses copper between two plated holes, and fills of the net on other
layers join the same two holes, the stretch is judged by the layers' widths
added, each scaled to the route's layer by the ratio of the two layers'
IPC-2221 needs. Pure: synthetic boards."""
import dataclasses

import pytest

from placemat.board_geometry import CopperItem
from placemat.checks import current_paths, ipc2221_width_mm
from placemat.geometry import circle_polygon
from placemat.values import Box, CopperLayer, Location
from tests.fixtures import board_geometry, footprint

F, IN1, B = CopperLayer.F, CopperLayer.IN1, CopperLayer.B
STEP = 0.05


@pytest.fixture(autouse=True)
def _widths_alone():
    """No neck is credited as short here: the verdicts are the widths'."""
    from placemat.settings import Settings, bind
    with bind(dataclasses.replace(Settings(), check_neck_end_share=1.0)):
        yield


def _necked(neck):
    """A fill 3 mm across from x 11 to 19, necked to `neck` mm from x 13 to
    17 round y 10: both parts' SW pads (x 11.4 and 18.6) lie in it."""
    h = neck / 2
    return ((11, 8.5), (13, 8.5), (13, 10 - h), (17, 10 - h), (17, 8.5), (19, 8.5), (19, 11.5), (17, 11.5),
            (17, 10 + h), (13, 10 + h), (13, 11.5), (11, 11.5))


def _zone(layer, poly):
    return CopperItem("zone", "SW", frozenset([layer]), (poly,), Box.of_points(poly))


def _via(x, y, layers, size=0.6):
    ring = circle_polygon(Location(x, y), size / 2)
    return CopperItem("via", "SW", frozenset(layers), (ring,), Box.of_points(ring), None, size, 0.3, ((x, y),))


def _parts(amps, through):
    q1 = footprint("Q1", 10, 10, nets=("GND", "SW"), fields={"Pm.I": amps}, through=through)
    l1 = footprint("L1", 20, 10, nets=("SW", "VOUT"), fields={"Pm.I": amps}, through=through)
    return [q1, l1]


def _sw(geometry):
    return {v.subject: v for v in current_paths(geometry)}["SW"]


def _layers(v):
    return {d["layer"]: d for d in v.facts["layers"]}


def test_two_outer_fills_joined_at_both_through_hole_pads_add_their_widths():
    """2.5 A needs 1.06 mm on 1 oz outer copper: the F fill's 0.6 mm neck
    and the B fill's 0.8 mm neck each fail alone, and pass together."""
    need = ipc2221_width_mm(2.5)
    g = board_geometry(_parts("2.5A", through=True), copper=[_zone(F, _necked(0.6)), _zone(B, _necked(0.8))])
    v = _sw(g)
    assert v.ok is True, v.note
    assert v.limit == pytest.approx(need)
    assert 1.4 - 2 * STEP - 1e-6 <= v.value <= 1.4 + 1e-6, v.note
    on = _layers(v)
    assert set(on) == {"F.Cu", "B.Cu"}
    assert 0.6 - STEP - 1e-6 <= on["F.Cu"]["width_mm"] <= 0.6 + 1e-6
    assert 0.8 - STEP - 1e-6 <= on["B.Cu"]["width_mm"] <= 0.8 + 1e-6
    assert on["F.Cu"]["scale"] == pytest.approx(1.0) and on["B.Cu"]["scale"] == pytest.approx(1.0)
    assert on["B.Cu"]["route"] is True and on["F.Cu"]["route"] is False      # the route's own layer is the wider
    assert "B.Cu" in v.note and "F.Cu" in v.note, v.note


def test_a_fill_that_reaches_only_one_end_is_not_in_parallel():
    """The B fill stops short of L1's pad: it joins the stretch at one end
    only, so the route is judged on F alone, as before."""
    short = ((11, 8.5), (16, 8.5), (16, 11.5), (11, 11.5))
    g = board_geometry(_parts("2.5A", through=True), copper=[_zone(F, _necked(0.6)), _zone(B, short)])
    v = _sw(g)
    assert v.ok is False, v.note
    assert 0.6 - STEP - 1e-6 <= v.value <= 0.6 + 1e-6, v.note
    assert set(_layers(v)) == {"F.Cu"}


def test_a_single_layer_route_keeps_its_verdict_and_names_its_layer():
    g = board_geometry(_parts("2.5A", through=False), copper=[_zone(F, _necked(0.6))])
    v = _sw(g)
    assert v.ok is False
    assert 0.6 - STEP - 1e-6 <= v.value <= 0.6 + 1e-6, v.note
    on = _layers(v)
    assert set(on) == {"F.Cu"} and on["F.Cu"]["route"] is True


def test_an_inner_and_an_outer_layer_are_each_scaled_by_their_own_need():
    """Vias in both SMD pads join F and In1. At 2 A an inner layer needs
    2.03 mm and an outer one 0.78: In1's 1.0 mm neck (the route's, the
    wider) and F's 0.6 mm each fail; F's width counts on In1 as
    0.6 * 2.03 / 0.78, and the two pass together."""
    need_in, need_out = ipc2221_width_mm(2.0, k=0.024), ipc2221_width_mm(2.0)
    copper = [_zone(F, _necked(0.6)), _zone(IN1, _necked(1.0)),
              _via(11.4, 10, (F, IN1)), _via(18.6, 10, (F, IN1))]
    g = dataclasses.replace(board_geometry(_parts("2A", through=False), copper=copper), layers=(F, IN1, B))
    v = _sw(g)
    on = _layers(v)
    assert set(on) == {"F.Cu", "In1.Cu"} and on["In1.Cu"]["route"] is True
    assert on["F.Cu"]["scale"] == pytest.approx(need_in / need_out)
    assert v.limit == pytest.approx(need_in)
    assert v.value == pytest.approx(on["In1.Cu"]["width_mm"] + on["F.Cu"]["width_mm"] * need_in / need_out)
    assert v.ok is True, v.note
