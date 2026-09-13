"""Copper is declared against pads and lanes, and planned after placement
against where the pads actually landed."""
import pytest

from placemat.layout import Board
from placemat.copper import Track, Via, Pour
from placemat.values import (Box, CopperLayer, Location, Net, Part, PadRef, Priority)
from tests.fixtures import footprint, snapshot


def make_board():
    fps = [footprint("J1", 5, 5, w=8, h=3, inst="j_in", nets=("V48", "GND")),
           footprint("R1", 20, 20, inst="r1", nets=("V48", "MID")),
           footprint("R2", 25, 20, inst="r2", nets=("MID", "GND")),
           footprint("H1", 40, 40, w=6, h=2, cell="pd", inst="pd.jumper", nets=("CANH", "CANH_S0")),
           footprint("F1", 40, 44, w=6, h=2, cell="pd", inst="pd.fuse", nets=("V48", "FUSE_OUT"))]
    return Board(snapshot(fps, cells=["pd"], width=100, height=100), edge_margin=1.0)


def test_a_track_between_pads_follows_the_placed_pads():
    b = make_board()
    b.place(Part("r1"), at=Location(30, 30))
    b.place(Part("r2"), at=Location(50, 30))
    b.track(Net("MID"), [PadRef(Part("r1"), "MID"), PadRef(Part("r2"), "MID")], layer=CopperLayer.F)
    plan = b.resolve()
    ops = plan.copper
    assert len(ops) == 1 and isinstance(ops[0], Track)
    t = ops[0]
    assert t.net == "MID" and t.layer is CopperLayer.F
    assert t.start == Location(31.4, 30) and t.end == Location(48.6, 30)     # pad centres after the move
    assert t.width == pytest.approx(0.2)                                     # the net class width


def test_a_pad_reference_with_an_unknown_net_fails_at_declaration():
    b = make_board()
    with pytest.raises(KeyError):
        b.track(Net("NOPE"), [PadRef(Part("r1"), "MID"), Location(0, 0)], layer=CopperLayer.F)
    with pytest.raises(KeyError):
        b.track(Net("MID"), [PadRef(Part("r1"), "NOPE"), Location(0, 0)], layer=CopperLayer.F)


def test_a_polyline_becomes_one_track_per_leg_and_vias_are_ops():
    b = make_board()
    b.track(Net("MID"), [Location(0, 0), Location(5, 0), Location(5, 5)], layer=CopperLayer.B, width=0.5)
    b.via(Net("MID"), Location(5, 5))
    plan = b.resolve()
    tracks = [o for o in plan.copper if isinstance(o, Track)]
    vias = [o for o in plan.copper if isinstance(o, Via)]
    assert len(tracks) == 2 and all(t.width == 0.5 and t.layer is CopperLayer.B for t in tracks)
    assert len(vias) == 1 and vias[0].at == Location(5, 5) and vias[0].drill == 0.3 and vias[0].size == 0.6


def test_a_pour_is_a_polygon_on_one_layer():
    b = make_board()
    b.pour(Net("V48"), [Location(0, 0), Location(10, 0), Location(10, 4), Location(0, 4)], layer=CopperLayer.F)
    plan = b.resolve()
    p = plan.copper[0]
    assert isinstance(p, Pour) and p.net == "V48" and len(p.points) == 4


def test_fixed_copper_is_planned_before_loose_parts_and_blocks_them():
    b = make_board()
    b.place(Part("j_in"), at=Location(10, 10))
    # a bar the loose part would otherwise settle on
    b.pour(Net("V48"), [Location(20, 18), Location(40, 18), Location(40, 22), Location(20, 22)],
           layer=CopperLayer.F, priority=Priority.FIXED)
    b.place(Part("r2"), near=Location(30, 20), radius=6.0, step=0.5)      # MID/GND: foreign to V48
    plan = b.resolve()
    r2 = plan.box("r2")
    bar = Box(20, 18, 40, 22)
    assert not r2.overlaps(bar.inflate(-0.01)), r2
    order = [s.item for s in plan.steps]
    assert order.index("pour V48") < order.index("r2")


def test_default_copper_is_planned_after_loose_parts():
    b = make_board()
    b.place(Part("r2"), near=Location(30, 20), radius=6.0, step=0.5)
    b.pour(Net("V48"), [Location(20, 18), Location(40, 18), Location(40, 22), Location(20, 22)],
           layer=CopperLayer.F)
    plan = b.resolve()
    order = [s.item for s in plan.steps]
    assert order.index("r2") < order.index("pour V48")


def test_fixed_copper_may_not_reference_a_searched_part():
    b = make_board()
    b.place(Part("r2"), near=Location(30, 20))
    with pytest.raises(ValueError):
        b.track(Net("MID"), [PadRef(Part("r2"), "MID"), Location(0, 0)], layer=CopperLayer.F,
                priority=Priority.FIXED)


def test_a_cell_pad_reference_follows_the_placed_cell():
    b = make_board()
    from placemat.values import Cell, CellPadRef
    b.place(Cell("pd"), center=Location(60, 60), rotation=0)
    b.track(Net("CANH"), [CellPadRef(Cell("pd"), net="CANH", ref_prefix="H"), Location(0, 0)],
            layer=CopperLayer.F)
    plan = b.resolve()
    t = plan.copper[0]
    # jumper pad 1 (CANH) sits 2.4 west of the jumper centre; the cell moved by (+20, +18)
    assert t.start == Location(40 - 2.4 + 20, 40 + 18)


def test_a_point_may_mix_a_fixed_coordinate_with_a_pads():
    from placemat.values import X, Y
    b = make_board()
    b.place(Part("r1"), at=Location(30, 30))
    b.track(Net("MID"), [PadRef(Part("r1"), "MID"), (10.0, Y(PadRef(Part("r1"), "MID"))),
                         (X(PadRef(Part("r1"), "MID"), dx=1.0), 50.0)], layer=CopperLayer.F)
    plan = b.resolve()
    t1, t2 = plan.copper
    assert t1.end == Location(10.0, 30.0)
    assert t2.end == Location(31.4 + 1.0, 50.0)


def test_a_finger_band_may_be_placed_around_a_pads_y():
    from placemat.copper import Pour
    from placemat.values import X, Y
    b = make_board()
    b.place(Part("r1"), at=Location(30, 30))
    pad = PadRef(Part("r1"), "MID")
    b.finger(Net("V48"), layer=CopperLayer.F, y_lo=Y(pad, -3.0), y_hi=Y(pad, 3.0), x_from=60.0, x_to=X(pad, 2.0))
    plan = b.resolve()
    p = [o for o in plan.copper if isinstance(o, Pour)][0]
    ys = sorted({y for _, y in p.points})
    xs = sorted({x for x, _ in p.points})
    assert ys == [27.0, 33.0] and xs == [33.4, 60.0]
